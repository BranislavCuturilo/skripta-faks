// Jedan omotac oko fetch-a. Greska servera stize kao Error sa citljivom porukom,
// pa poziv na mestu upotrebe nikad ne mora da gleda status kod.

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, body, options = {}) {
  const init = { method, headers: {} };

  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  const response = await fetch(path, init);
  const type = response.headers.get('Content-Type') || '';

  if (options.raw) {
    if (!response.ok) throw new ApiError(`Poziv nije uspeo (${response.status}).`, response.status);
    return response.blob();
  }

  let payload = null;
  if (type.includes('application/json')) {
    payload = await response.json();
  } else {
    payload = { ok: response.ok, text: await response.text() };
  }

  if (!response.ok || payload.ok === false) {
    throw new ApiError(payload.error || `Poziv nije uspeo (${response.status}).`,
                       response.status, payload.detail);
  }
  return payload;
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  patch: (path, body) => request('PATCH', path, body),
  del: (path) => request('DELETE', path),
  blob: (path, body) => request('POST', path, body, { raw: true }),

  upload(path, files, fields = {}) {
    const form = new FormData();
    for (const [key, value] of Object.entries(fields)) form.append(key, value);
    for (const file of files) form.append('files', file, file.name);
    return request('POST', path, form);
  },
};

// Prati posao u pozadini dok ne zavrsi. `onTick` dobija svaki medjukorak.
export async function followJob(jobId, onTick) {
  for (;;) {
    const { job } = await api.get(`/api/jobs/${jobId}`);
    if (onTick) onTick(job);
    if (job.status !== 'running') return job;
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}
