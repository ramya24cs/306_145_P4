// Thin HTTP client: React -> (Vite proxy) -> Flask REST API. Methods: GET, POST, PUT, DELETE.
const BASE = import.meta.env.VITE_API_URL || "/api";

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Cannot reach the Flask API. Start the backend with 'python app.py' (port 5000).", 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new ApiError((data && data.error) || `Request failed (HTTP ${res.status})`, res.status, data);
  return data;
}

const qs = (params = {}) => {
  const p = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null));
  return p.toString() ? `?${p}` : "";
};

export const api = {
  health: () => request("GET", "/health"),
  validate: (patient_id) => request("POST", "/validate/patient-id", { patient_id }),
  classify: (report_code) => request("POST", "/classify", { report_code }),
  submitReport: (payload) => request("POST", "/reports", payload),
  reports: (params) => request("GET", "/reports" + qs(params)),
  report: (id) => request("GET", `/reports/${encodeURIComponent(id)}`),
  updateStatus: (id, payload) => request("PUT", `/reports/${encodeURIComponent(id)}/status`, payload),
  claim: (id, handler_id) => request("POST", `/reports/${encodeURIComponent(id)}/claim`, { handler_id }),
  fixZone: (id, ward_zone) => request("PUT", `/reports/${encodeURIComponent(id)}/zone`, { ward_zone }),
  deleteReport: (id) => request("DELETE", `/reports/${encodeURIComponent(id)}`),
  doctors: () => request("GET", "/doctors"),
  doctor: (id) => request("GET", `/doctors/${id}`),
  setAvailability: (id, available) => request("PUT", `/doctors/${id}/availability`, { available }),
  setCapacity: (id, max_capacity) => request("PUT", `/doctors/${id}/capacity`, { max_capacity }),
  routingTable: () => request("GET", "/routing/table"),
  queue: (name) => request("GET", `/queues/${name}`),
  advanceClock: (minutes) => request("POST", "/simulation/advance", { minutes }),
  analytics: () => request("GET", "/analytics"),
};
