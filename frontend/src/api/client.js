/**
 * Axios API client for SynthSense.
 * All backend calls go through this module so the base URL is configured once.
 */
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const client = axios.create({
  baseURL: API_BASE,
  timeout: 120_000, // 2 minutes — agent pipelines can be slow
});

// ── Incidents ─────────────────────────────────────────────────────────────────

export async function submitIncident(description, imageFile) {
  const form = new FormData();
  form.append("description", description);
  if (imageFile) {
    form.append("image", imageFile);
  }
  const { data } = await client.post("/incidents", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getIncident(id) {
  const { data } = await client.get(`/incidents/${id}`);
  return data;
}

export async function listIncidents(limit = 20) {
  const { data } = await client.get("/incidents", { params: { limit } });
  return data;
}

/**
 * Stream agent progress via POST fetch (SSE over fetch ReadableStream).
 * Supports large base64 image payloads that would exceed URL length limits.
 * Returns an async iterator — use `for await (const event of streamIncidentPost(...))`.
 *
 * @param {string} incidentId
 * @param {string} description
 * @param {string} imageB64 - base64-encoded image (no data URL prefix)
 * @returns {AsyncGenerator<object>}
 */
export async function* streamIncidentPost(incidentId, description = "", imageB64 = "") {
  const response = await fetch(`${API_BASE}/incidents/${incidentId}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description, image_b64: imageB64 }),
  });

  if (!response.ok) {
    throw new Error(`Stream request failed: HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ") && line.length > 6) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {
          // malformed SSE line — skip
        }
      }
    }
  }
}

/** @deprecated Use streamIncidentPost for new code (supports image payloads). */
export function streamIncident(incidentId, description = "") {
  const params = new URLSearchParams({ description });
  const url = `${API_BASE}/incidents/${incidentId}/stream?${params}`;
  return new EventSource(url);
}

// ── Runbooks ──────────────────────────────────────────────────────────────────

export async function uploadRunbook(pdfFile) {
  const form = new FormData();
  form.append("file", pdfFile);
  const { data } = await client.post("/runbooks/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

// ── Quality scores ────────────────────────────────────────────────────────────

export async function getLatestScores() {
  const { data } = await client.get("/evals/latest");
  return data;
}

export async function getAllScores() {
  const { data } = await client.get("/evals/all");
  return data;
}

// ── Health ────────────────────────────────────────────────────────────────────

export async function checkHealth() {
  const { data } = await client.get("/health");
  return data;
}
