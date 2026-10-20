const API = 'https://localmark.ai/api/v1';
const searchForm = document.querySelector('#search-form');
const verifyForm = document.querySelector('#verify-form');
const results = document.querySelector('#results');
const resultTitle = document.querySelector('#results-heading');
const resultCount = document.querySelector('#result-count');
const verifySection = document.querySelector('#verify-section');
const verifyResult = document.querySelector('#verify-result');
const loadMore = document.querySelector('#load-more');
let searchParams = null;
let shown = 0;

function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
}

function safeLink(label, url) {
  try {
    const parsed = new URL(url);
    if (!['https:', 'http:'].includes(parsed.protocol)) return el('span', '', label);
    const link = el('a', '', label);
    link.href = parsed.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  } catch {
    return el('span', '', label);
  }
}

function dateLabel(value) {
  if (!value) return 'No recent observation';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString('en-GB', {dateStyle:'medium', timeStyle:'short', timeZone:'UTC'}) + ' UTC';
}

function probeLabel(probe) {
  return ({a2a_response:'A2A response confirmed', auth_required:'Requires authentication',
    jsonrpc_no_task_lookup:'JSON-RPC answered; task lookup not supported',
    not_supported:'Transport not tested', unsupported_transport:'Transport not tested',
    unconfirmed:'A2A response not confirmed'})[probe?.state] || 'A2A response not confirmed';
}

function pill(text, warning = false) {
  return el('span', warning ? 'pill warn' : 'pill', text);
}

async function getJson(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
  const response = await fetch(url, {headers: {'Accept': 'application/json'}, signal:controller.signal, credentials:'omit', referrerPolicy:'no-referrer'});
  if (!response.ok) {
    let detail = `LocalMark returned ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch { /* Keep status. */ }
    if (response.status === 429) detail = 'Please wait before trying again. LocalMark is rate limiting this request.';
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return await response.json();
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The request timed out. Please try again.');
    throw error;
  } finally { clearTimeout(timer); }
}

function showNotice(container, message) {
  container.replaceChildren(el('div', 'notice', message));
}

function agentCard(agent) {
  const article = el('article', 'card');
  article.append(el('h3', '', agent.name || 'Unnamed agent'));
  const description = agent.description || 'The publisher has not provided a description.';
  article.append(el('p', '', description.length > 240 ? description.slice(0, 237).replace(/\s+\S*$/, '') + '…' : description));
  if (agent.recommendation) {
    const matching = agent.recommendation.capability_match === 'related' ? 'Related declaration; the full operation is not explicit. ' : '';
    article.append(el('p', 'hint', matching + (agent.match_reasons || agent.recommendation.reasons || []).slice(0, 3).join(' ')));
  }
  const meta = el('div', 'meta');
  meta.append(pill(`Card checked: ${dateLabel(agent.last_verified)}`));
  const probe = agent.read_only_a2a_probe;
  if (probe?.state === 'a2a_response') meta.append(pill(`A2A answered: ${dateLabel(probe.checked_at)}`));
  else meta.append(pill(probeLabel(probe), true));
  if (agent.endpoint_tls?.reachable === true) meta.append(pill('Endpoint TLS reached'));
  if (agent.signature_status === 'verified') meta.append(pill('Signature verified'));
  article.append(meta);
  const links = el('div', 'links');
  links.append(safeLink('Evidence profile ↗', `https://localmark.ai/agents/${encodeURIComponent(agent.id)}`));
  links.append(safeLink('Connection metadata (JSON) ↗', `${API}/connection-plan?target=${encodeURIComponent(agent.id)}`));
  links.append(safeLink('Watch changes ↗', `https://localmark.ai/watch?agent_id=${encodeURIComponent(agent.id)}`));
  if (agent.card_url) links.append(safeLink('Publisher Agent Card ↗', agent.card_url));
  article.append(links);
  return article;
}

searchForm.addEventListener('submit', async event => {
  event.preventDefault();
  const query = document.querySelector('#query').value.trim();
  if (!query) return;
  const params = new URLSearchParams({q: query, limit: '20'});
  if (document.querySelector('#recent-card').checked) params.set('checked_within_hours', '24');
  if (document.querySelector('#recent-a2a').checked) params.set('a2a_response_within_hours', '24');
  if (document.querySelector('#tls').checked) params.set('tls_reachable', 'true');
  searchParams = params;
  shown = 0;
  loadMore.hidden = true;
  resultTitle.textContent = `Agents for “${query}”`;
  resultCount.textContent = '';
  showNotice(results, 'Searching LocalMark…');
  searchForm.querySelector('button').disabled = true;
  results.setAttribute('aria-busy', 'true');
  try {
    const data = await getJson(`${API}/search?${params}`);
    const items = Array.isArray(data.items) ? data.items : [];
    shown = items.length;
    resultCount.textContent = `${shown} shown`;
    loadMore.hidden = items.length < 20;
    if (data.status === 'needs_clarification') {
      const issues = (data.interpreted_query?.unsupported_constraints || []).map(v => `${v.constraint}: ${v.reason}`).join(' ');
      showNotice(results, `Please clarify the requested conditions. ${issues} Use LocalMark’s Find by task page to choose explicit evidence and payment filters.`);
    } else if (!items.length) showNotice(results, 'No matching agents found with these evidence filters. Try a broader term or turn off a filter.');
    else results.replaceChildren(...items.map(agentCard));
  } catch (error) {
    showNotice(results, `Search unavailable: ${error.message}`);
  } finally { searchForm.querySelector('button').disabled = false; results.removeAttribute('aria-busy'); }
});

loadMore.addEventListener('click', async () => {
  if (!searchParams) return;
  loadMore.disabled = true;
  searchForm.querySelector('button').disabled = true;
  const params = new URLSearchParams(searchParams);
  params.set('offset', String(shown));
  try {
    const data = await getJson(`${API}/search?${params}`);
    const items = Array.isArray(data.items) ? data.items : [];
    results.append(...items.map(agentCard));
    shown += items.length;
    resultCount.textContent = `${shown} shown`;
    loadMore.hidden = items.length < 20;
    loadMore.textContent = 'Load more agents';
  } catch (error) { loadMore.textContent = `Retry loading more: ${error.message}`; }
  finally { loadMore.disabled = false; searchForm.querySelector('button').disabled = false; }
});

function detailRow(list, label, value) {
  if (value === null || value === undefined || value === '') return;
  const wrap = el('div');
  wrap.append(el('dt', '', label), el('dd', '', value));
  list.append(wrap);
}

function renderVerify(data) {
  const box = el('div', 'card');
  const status = data.listing_status || 'unknown';
  if (data.matched_by === 'publisher_domain') {
    box.append(el('h3', '', data.publisher_domain || 'Publisher listings'));
    box.append(el('p', '', `${data.total_matches || data.matches?.length || 0} public agents grouped under this publisher domain. Grouping does not verify ownership or the behaviour of any individual endpoint.`));
    const list = el('ul', 'publisher-matches');
    for (const match of data.matches || []) {
      const item = el('li');
      item.append(safeLink(`${match.name || 'Unnamed agent'} — evidence profile ↗`, `https://localmark.ai/agents/${encodeURIComponent(match.agent_id)}`));
      list.append(item);
    }
    box.append(list);
    if (data.all_matches_url) box.append(safeLink(`All ${data.total_matches} listings (JSON) ↗`, data.all_matches_url));
    if (data.root_card_review) box.append(el('p', 'hint', `Separate root-card status: ${data.root_card_review.status?.replaceAll('_',' ') || 'unknown'} (${data.root_card_review.reason_category?.replaceAll('_',' ') || 'no category'}). This applies to that card, not every agent from the publisher.`));
    verifyResult.replaceChildren(box);
    return;
  }
  box.append(el('h3', '', data.name || (status === 'not_seen' ? 'Address not seen by LocalMark' : 'Listing evidence')));
  box.append(el('p', '', status === 'listed'
    ? 'LocalMark has stored observations for this listing. Check the evidence below before connecting.'
    : data.review_status === 'held_for_review'
      ? 'This card was held for review. The flag is not a finding of impersonation or fraud.'
      : 'LocalMark has no public listing for this address. This is not a finding that the agent is unsafe.'));
  const meta = el('div', 'meta');
  meta.append(pill(status.replaceAll('_', ' '), status !== 'listed'));
  if (data.read_only_a2a_probe?.state === 'a2a_response') meta.append(pill('Read-only A2A response observed'));
  if (data.signature?.status === 'verified') meta.append(pill('Signature verified'));
  box.append(meta);
  const details = el('dl', 'verify-details');
  detailRow(details, 'Matched by', data.matched_by?.replaceAll('_', ' '));
  detailRow(details, 'Intake status', data.review_status?.replaceAll('_', ' '));
  detailRow(details, 'Review category', data.reason_category?.replaceAll('_', ' '));
  if (data.card_reachability?.latest?.checked_at) detailRow(details, 'Card last checked', dateLabel(data.card_reachability.latest.checked_at));
  detailRow(details, 'Endpoint TLS', data.endpoint_tls?.success === true ? 'Reached' : data.endpoint_tls?.success === false ? 'Not reached' : null);
  if (data.read_only_a2a_probe) detailRow(details, 'A2A probe', probeLabel(data.read_only_a2a_probe));
  if (data.first_listed_at) detailRow(details, 'First listed', dateLabel(data.first_listed_at));
  if (details.children.length) box.append(details);
  const lookalikes = data.domain_lookalike_assessment?.possible_lookalikes;
  if (Array.isArray(lookalikes) && lookalikes.length) {
    box.append(el('p', '', `Similar looking publisher domains: ${lookalikes.join(', ')}. Spelling similarity alone does not establish impersonation.`));
  }
  const links = el('div', 'links');
  if (data.profile_url) links.append(safeLink('Full evidence profile ↗', data.profile_url));
  if (data.card_url) links.append(safeLink('Publisher Agent Card ↗', data.card_url));
  if (links.children.length) box.append(links);
  verifyResult.replaceChildren(box);
}

verifyForm.addEventListener('submit', async event => {
  event.preventDefault();
  const target = document.querySelector('#target').value.trim();
  if (!target) return;
  verifySection.hidden = false;
  showNotice(verifyResult, 'Checking LocalMark’s stored evidence…');
  verifyForm.querySelector('button').disabled = true;
  verifyResult.setAttribute('aria-busy', 'true');
  try {
    const params = new URLSearchParams({card_url: target});
    renderVerify(await getJson(`${API}/verify?${params}`));
  } catch (error) {
    showNotice(verifyResult, `Verification lookup unavailable: ${error.message}`);
  } finally { verifyForm.querySelector('button').disabled = false; verifyResult.removeAttribute('aria-busy'); }
  verifySection.scrollIntoView({behavior:'smooth', block:'start'});
});
