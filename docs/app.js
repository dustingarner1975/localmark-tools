const API = 'https://localmark.ai/api/v1';
const searchForm = document.querySelector('#search-form');
const verifyForm = document.querySelector('#verify-form');
const results = document.querySelector('#results');
const resultTitle = document.querySelector('#results-heading');
const resultCount = document.querySelector('#result-count');
const verifySection = document.querySelector('#verify-section');
const verifyResult = document.querySelector('#verify-result');

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
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleString(undefined, {dateStyle:'medium', timeStyle:'short'});
}

function pill(text, warning = false) {
  return el('span', warning ? 'pill warn' : 'pill', text);
}

async function getJson(url) {
  const response = await fetch(url, {headers: {'Accept': 'application/json'}});
  if (!response.ok) {
    let detail = `LocalMark returned ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch { /* Keep status. */ }
    if (response.status === 429) detail = 'Please wait before trying again. LocalMark is rate limiting this request.';
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return response.json();
}

function showNotice(container, message) {
  container.replaceChildren(el('div', 'notice', message));
}

function agentCard(agent) {
  const article = el('article', 'card');
  article.append(el('h3', '', agent.name || 'Unnamed agent'));
  const description = agent.description || 'The publisher has not provided a description.';
  article.append(el('p', '', description.length > 240 ? description.slice(0, 237).replace(/\s+\S*$/, '') + '…' : description));
  const meta = el('div', 'meta');
  meta.append(pill(`Card checked: ${dateLabel(agent.last_verified)}`));
  const probe = agent.read_only_a2a_probe;
  if (probe?.state === 'a2a_response') meta.append(pill(`A2A answered: ${dateLabel(probe.checked_at)}`));
  else meta.append(pill('A2A response not confirmed', true));
  if (agent.endpoint_tls?.reachable === true) meta.append(pill('Endpoint TLS reached'));
  if (agent.signature_status === 'verified') meta.append(pill('Signature verified'));
  article.append(meta);
  const links = el('div', 'links');
  links.append(safeLink('Evidence profile ↗', `https://localmark.ai/agents/${encodeURIComponent(agent.id)}`));
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
  resultTitle.textContent = `Agents for “${query}”`;
  resultCount.textContent = '';
  showNotice(results, 'Searching LocalMark…');
  try {
    const data = await getJson(`${API}/search?${params}`);
    const items = Array.isArray(data.items) ? data.items : [];
    resultCount.textContent = `${items.length} shown`;
    if (!items.length) showNotice(results, 'No matching agents found with these evidence filters. Try a broader term or turn off a filter.');
    else results.replaceChildren(...items.map(agentCard));
  } catch (error) {
    showNotice(results, `Search unavailable: ${error.message}`);
  }
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
  detailRow(details, 'Card last checked', dateLabel(data.card_reachability?.latest?.checked_at));
  detailRow(details, 'Endpoint TLS', data.endpoint_tls?.success === true ? 'Reached' : data.endpoint_tls?.success === false ? 'Not reached' : null);
  detailRow(details, 'A2A probe', data.read_only_a2a_probe?.state?.replaceAll('_', ' '));
  detailRow(details, 'First listed', dateLabel(data.first_listed_at));
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
  try {
    const params = new URLSearchParams({card_url: target});
    renderVerify(await getJson(`${API}/verify?${params}`));
  } catch (error) {
    showNotice(verifyResult, `Verification lookup unavailable: ${error.message}`);
  }
  verifySection.scrollIntoView({behavior:'smooth', block:'start'});
});
