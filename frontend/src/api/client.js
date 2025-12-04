/**
 * API Client for Multi-Agent Behavioral Testing Platform
 */

export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Helper for error handling
async function handleResponse(response) {
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

// ============================================================================
// Graph Management
// ============================================================================

export async function fetchGraphs(params = {}) {
  const query = new URLSearchParams(params).toString();
  const url = query ? `${API}/graphs?${query}` : `${API}/graphs`;
  const res = await fetch(url);
  return handleResponse(res);
}

export async function fetchGraph(id) {
  const res = await fetch(`${API}/graphs/${id}`);
  return handleResponse(res);
}

export async function uploadGraph(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API}/graphs/upload`, {
    method: "POST",
    body: form
  });
  return handleResponse(res);
}

export async function createGraph(graphData) {
  const res = await fetch(`${API}/graphs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(graphData)
  });
  return handleResponse(res);
}

export async function updateGraph(id, updates) {
  const res = await fetch(`${API}/graphs/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates)
  });
  return handleResponse(res);
}

export async function deleteGraph(id) {
  const res = await fetch(`${API}/graphs/${id}`, { method: "DELETE" });
  return handleResponse(res);
}

export async function validateGraph(id) {
  const res = await fetch(`${API}/graphs/${id}/validate`);
  return handleResponse(res);
}

export async function exportGraph(id, format = "yaml") {
  const res = await fetch(`${API}/graphs/${id}/export?format=${format}`);
  return handleResponse(res);
}

// ============================================================================
// Test Runs
// ============================================================================

export async function runGraph(id, config = {}) {
  const res = await fetch(`${API}/runs/${id}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config)
  });
  return handleResponse(res);
}

export async function runGraphAsync(id, config = {}) {
  const res = await fetch(`${API}/runs/${id}/execute/async`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config)
  });
  return handleResponse(res);
}

export async function fetchRuns(params = {}) {
  const query = new URLSearchParams(params).toString();
  const url = query ? `${API}/runs?${query}` : `${API}/runs`;
  const res = await fetch(url);
  return handleResponse(res);
}

export async function fetchRun(id) {
  const res = await fetch(`${API}/runs/${id}`);
  return handleResponse(res);
}

export async function fetchRunTrace(id) {
  const res = await fetch(`${API}/runs/${id}/trace`);
  return handleResponse(res);
}

export async function deleteRun(id) {
  const res = await fetch(`${API}/runs/${id}`, { method: "DELETE" });
  return handleResponse(res);
}

// ============================================================================
// Metrics
// ============================================================================

export async function fetchMetrics() {
  const res = await fetch(`${API}/metrics/summary`);
  return handleResponse(res);
}

export async function fetchGraphMetrics(graphId) {
  const res = await fetch(`${API}/metrics/by-graph/${graphId}`);
  return handleResponse(res);
}

export async function fetchTrends(days = 7, graphId = null) {
  let url = `${API}/metrics/trends?days=${days}`;
  if (graphId) url += `&graph_id=${graphId}`;
  const res = await fetch(url);
  return handleResponse(res);
}

export async function fetchLatencyDistribution(graphId = null) {
  let url = `${API}/metrics/latency-distribution`;
  if (graphId) url += `?graph_id=${graphId}`;
  const res = await fetch(url);
  return handleResponse(res);
}

export async function fetchAssertionMetrics(graphId = null) {
  let url = `${API}/metrics/assertions`;
  if (graphId) url += `?graph_id=${graphId}`;
  const res = await fetch(url);
  return handleResponse(res);
}

export async function fetchCostBreakdown() {
  const res = await fetch(`${API}/metrics/cost-breakdown`);
  return handleResponse(res);
}

export async function detectDrift(graphId, threshold = 0.15) {
  const res = await fetch(`${API}/metrics/drift?graph_id=${graphId}&threshold=${threshold}`);
  return handleResponse(res);
}

// ============================================================================
// Authentication
// ============================================================================

let authToken = localStorage.getItem("auth_token");

export function setAuthToken(token) {
  authToken = token;
  if (token) {
    localStorage.setItem("auth_token", token);
  } else {
    localStorage.removeItem("auth_token");
  }
}

export function getAuthHeaders() {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

export async function login(email, password) {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password })
  });
  const data = await handleResponse(res);
  setAuthToken(data.access_token);
  return data;
}

export async function logout() {
  setAuthToken(null);
}

export async function getCurrentUser() {
  const res = await fetch(`${API}/auth/me`, {
    headers: getAuthHeaders()
  });
  return handleResponse(res);
}

// ============================================================================
// Health Check
// ============================================================================

export async function healthCheck() {
  const res = await fetch(`${API}/health`);
  return handleResponse(res);
}

export async function getProviders() {
  const res = await fetch(`${API}/providers`);
  return handleResponse(res);
}
