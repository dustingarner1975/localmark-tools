"""Reproducible monthly summaries of public daily snapshots, not Internet-wide estimates."""
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import re


def snapshot_metrics(records):
    count=signed=confirmed=tls=claimed=0
    publishers=set()
    tag_publishers=defaultdict(set)
    for row in records:
        count+=1
        obs=row.get('observations') or {}
        signed+=obs.get('signature_status')=='verified'
        confirmed+=(obs.get('read_only_a2a_probe') or {}).get('state')=='a2a_response'
        tls+=(obs.get('endpoint_tls') or {}).get('passed') is True
        claimed+=obs.get('domain_claimed') is True
        publisher=row.get('publisher_domain') or ''
        if publisher:
            publishers.add(publisher)
            for skill in (row.get('publisher_declared') or {}).get('skills',[]):
                for tag in skill.get('tags',[]):
                    if isinstance(tag,str) and 1<=len(tag)<=80:
                        tag_publishers[tag.casefold()].add(publisher)
    pct=lambda n:round(100*n/count,2) if count else None
    return {'public_agents':count,'distinct_publishers':len(publishers),
            'verified_signatures':signed,'verified_signature_percent':pct(signed),
            'confirmed_read_only_a2a_responses':confirmed,'confirmed_a2a_percent':pct(confirmed),
            'endpoint_tls_passed':tls,'endpoint_tls_percent':pct(tls),
            'domain_claimed':claimed,'domain_claimed_percent':pct(claimed),
            'common_declared_tags':[{'tag':tag,'distinct_publishers':len(owners)}
                for tag,owners in sorted(tag_publishers.items(),key=lambda item:(-len(item[1]),item[0]))[:10]]}


def read_snapshot(path):
    opener=gzip.open if path.suffix=='.gz' else open
    size=0
    with opener(path,'rb') as source:
        for i,line in enumerate(source):
            size+=len(line)
            if i>=100000 or len(line)>131072 or size>200_000_000:
                raise ValueError('Snapshot exceeds report processing limits')
            if line.strip():
                yield json.loads(line)


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    encoded=(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(encoded)
    temporary.chmod(0o644)
    temporary.replace(path)


def generate_reports(export_dir, now=None):
    root=Path(export_dir)
    now=now or datetime.now(timezone.utc)
    current=now.strftime('%Y-%m')
    months=defaultdict(list)
    for file in sorted(root.glob('????-??-??.json')):
        try:
            date=datetime.strptime(file.stem,'%Y-%m-%d').date()
            if date>now.date():
                continue
            manifest=json.loads(file.read_text(encoding='utf-8'))
            data=root/(date.isoformat()+'.jsonl.gz')
            if not data.is_file():
                continue
            months[date.strftime('%Y-%m')].append((date,manifest,data))
        except (OSError,ValueError,TypeError):
            continue
    out=root/'reports'
    changed=[]
    for month,snapshots in months.items():
        path=out/(month+'.json')
        if path.is_file():
            prior=json.loads(path.read_text())
            if prior.get('calendar_month_closed'):
                continue
        else:
            prior={}
        # A current-day rewrite or damaged source must not hide behind the
        # generated report's date. Validate bytes even when no rerender is due.
        for _,manifest,data in snapshots:
            if data.stat().st_size>100_000_000 or hashlib.sha256(data.read_bytes()).hexdigest()!=manifest.get('gzip_sha256'):
                raise ValueError('Snapshot checksum mismatch; report not published')
        source_pairs=[(date.isoformat(),manifest['gzip_sha256']) for date,manifest,_ in snapshots]
        prior_pairs=[(day['snapshot_date'],day['gzip_sha256']) for day in prior.get('daily_snapshots',[])]
        if month==current and source_pairs==prior_pairs:
            continue
        days=[]
        for date,manifest,data in snapshots:
            metrics=snapshot_metrics(read_snapshot(data))
            if metrics['public_agents']!=manifest['record_count']:
                raise ValueError('Snapshot record count mismatch; report not published')
            days.append({'snapshot_date':date.isoformat(),'source_url':'/data/'+data.name,
                         'gzip_sha256':manifest['gzip_sha256'],**metrics})
        report={'schema_version':'1','month':month,'generated_at':now.isoformat(),
            'title':'State of the agent web — '+datetime.strptime(month,'%Y-%m').strftime('%B %Y'),
            'calendar_month_closed':month<current,'observed_days':len(days),
            'first_snapshot_date':days[0]['snapshot_date'],'latest_snapshot_date':days[-1]['snapshot_date'],
            'first':days[0],'latest':days[-1],'daily_snapshots':days,
            'net_listing_count_change':days[-1]['public_agents']-days[0]['public_agents'],
            'scope':'Public Agent Cards included in available LocalMark daily snapshots. This is not an estimate of every Internet agent, continuous uptime or task success.',
            'limitations':['Observation begins on the first available snapshot date, which may be mid-month.',
                'Listing totals change through discovery, failures, removals and duplicate consolidation. Net change does not equal newly created agents.',
                'A signature result, ownership claim and read-only protocol response are separate observations, not certification.',
                'Capability tests, where opted in, are separate from the read-only protocol response counts here.'],
            'license':'https://creativecommons.org/licenses/by/4.0/',
            'attribution':'Data: LocalMark (localmark.ai)',
            'methodology':'Verify each source gzip SHA-256 and record count, then count public records and observation fields. Rank declared tags by distinct publisher_domain values. Code is published with the developer tools.'}
        write_json(path,report)
        changed.append(month)
    available=[]
    for path in sorted(out.glob('????-??.json'),reverse=True):
        if path.stem=='index':
            continue
        item=json.loads(path.read_text())
        available.append({key:item[key] for key in ('month','title','observed_days','calendar_month_closed','first_snapshot_date','latest_snapshot_date')}
                         | {'url':'/reports/'+path.stem,'json_url':'/api/v1/reports/'+path.stem})
    write_json(out/'index.json',{'schema_version':'1','reports':available})
    return {'updated':changed,'available':len(available)}


def render_report(report):
    import ui
    latest=report['latest']
    stage='Closed calendar month' if report['calendar_month_closed'] else 'Month to date'
    rows=''.join(f'<tr><th scope="row">{ui.esc(day["snapshot_date"])}</th><td>{day["public_agents"]:,}</td><td>{day["distinct_publishers"]:,}</td><td>{day["verified_signature_percent"]}%</td><td>{day["confirmed_a2a_percent"]}%</td></tr>' for day in report['daily_snapshots'])
    tags=''.join(f'<li>{ui.esc(tag["tag"])} — {tag["distinct_publishers"]} publishers</li>' for tag in latest['common_declared_tags'])
    limits=''.join('<li>'+ui.esc(value)+'</li>' for value in report['limitations'])
    body=f'''<div class="wrap policy-page"><div class="page-hero"><div class="eyebrow">{stage} · {report['observed_days']} daily snapshots</div><h1>{ui.esc(report['title'])}</h1><p>Observed {ui.esc(report['first_snapshot_date'])} through {ui.esc(report['latest_snapshot_date'])}. These figures describe the public cards in LocalMark’s snapshots.</p></div><div class="metric-grid"><div class="surface"><strong>{latest['public_agents']:,}</strong><span>Public agents in latest snapshot</span></div><div class="surface"><strong>{latest['distinct_publishers']:,}</strong><span>Publisher domains</span></div><div class="surface"><strong>{latest['verified_signature_percent']}%</strong><span>Verified card signatures</span></div><div class="surface"><strong>{latest['confirmed_a2a_percent']}%</strong><span>Read-only A2A response confirmed</span></div></div><section class="surface"><h2>What moved</h2><p>The listed-agent total changed by {report['net_listing_count_change']:+,} between these snapshots. Discovery, removals, check failures and merged alternate addresses can all change this number.</p><div class="benchmark-table"><table><thead><tr><th>UTC snapshot</th><th>Agents</th><th>Publishers</th><th>Signed</th><th>A2A responding</th></tr></thead><tbody>{rows}</tbody></table></div></section><section class="surface"><h2>Common publisher-declared tags</h2><ul>{tags}</ul><h2>Method and limits</h2><p>{ui.esc(report['methodology'])}</p><ul>{limits}</ul><p><a href="/api/v1/reports/{report['month']}">Download this report as JSON</a> · <a href="/data/index.json">Source snapshots and checksums</a> · <a href="https://github.com/dustingarner1975/localmark-tools" target="_blank" rel="noopener noreferrer">Reproduction code ↗</a></p><p>Credit: Data: LocalMark (localmark.ai), CC BY 4.0. Publisher-supplied content remains outside LocalMark’s licence.</p></section><p><a href="/reports">All reports →</a></p></div>'''
    return ui.shell(report['title'],'A reproducible snapshot report on public Agent Cards, publisher coverage, signatures and read-only A2A observations.','',body,path='/reports/'+report['month'])
