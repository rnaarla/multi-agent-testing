import { useEffect, useState, useCallback } from "react";
import {
  fetchGraphs,
  runGraph,
  fetchMetrics,
  fetchRuns,
  startSimulationRun,
  listSimulationRuns,
  getSimulationRun,
  getSimulationEvents,
  evaluateSimulationRun
} from "../api/client";

/** Preset assertions for the dashboard demo (targets: run, simulation, agent_id). */
const DEMO_SIMULATION_ASSERTIONS = [
  { id: "run-completed", type: "equals", target: "run", field: "status", expected: "completed" },
  { id: "has-telemetry", type: "greater_than", target: "simulation", field: "event_count", expected: 0 }
];

// Styles
const styles = {
  container: {
    maxWidth: "1400px",
    margin: "0 auto",
    padding: "20px",
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
  },
  simulationLayout: {
    display: "grid",
    gridTemplateColumns: "300px 1fr",
    gap: "20px",
    alignItems: "start"
  },
  simulationRuns: {
    background: "white",
    borderRadius: "12px",
    border: "1px solid #e0e0e0",
    overflow: "hidden"
  },
  simulationRunItem: {
    padding: "15px",
    borderBottom: "1px solid #f0f0f0",
    cursor: "pointer"
  },
  simulationRunItemActive: {
    background: "#eef2ff"
  },
  simulationPanel: {
    background: "white",
    borderRadius: "12px",
    border: "1px solid #e0e0e0",
    padding: "20px"
  },
  eventList: {
    marginTop: "20px",
    maxHeight: "400px",
    overflow: "auto",
    borderTop: "1px solid #f0f0f0"
  },
  eventItem: {
    padding: "12px 0",
    borderBottom: "1px solid #f5f5f5"
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "30px",
    borderBottom: "2px solid #e0e0e0",
    paddingBottom: "20px"
  },
  title: {
    fontSize: "28px",
    fontWeight: "600",
    color: "#1a1a1a",
    margin: 0
  },
  metricsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: "20px",
    marginBottom: "30px"
  },
  metricCard: {
    background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
    borderRadius: "12px",
    padding: "20px",
    color: "white",
    boxShadow: "0 4px 15px rgba(102, 126, 234, 0.3)"
  },
  metricValue: {
    fontSize: "32px",
    fontWeight: "700",
    marginBottom: "5px"
  },
  metricLabel: {
    fontSize: "14px",
    opacity: 0.9
  },
  tabs: {
    display: "flex",
    gap: "10px",
    marginBottom: "20px",
    borderBottom: "1px solid #e0e0e0",
    paddingBottom: "10px"
  },
  tab: {
    padding: "10px 20px",
    border: "none",
    background: "transparent",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: "500",
    color: "#666",
    borderRadius: "8px",
    transition: "all 0.2s"
  },
  tabActive: {
    background: "#667eea",
    color: "white"
  },
  graphsGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(350px, 1fr))",
    gap: "20px"
  },
  graphCard: {
    border: "1px solid #e0e0e0",
    borderRadius: "12px",
    padding: "20px",
    background: "white",
    boxShadow: "0 2px 8px rgba(0,0,0,0.05)",
    transition: "transform 0.2s, box-shadow 0.2s"
  },
  graphCardHover: {
    transform: "translateY(-2px)",
    boxShadow: "0 4px 20px rgba(0,0,0,0.1)"
  },
  graphName: {
    fontSize: "18px",
    fontWeight: "600",
    marginBottom: "10px",
    color: "#1a1a1a"
  },
  graphStats: {
    display: "flex",
    gap: "15px",
    marginBottom: "15px",
    fontSize: "13px",
    color: "#666"
  },
  button: {
    padding: "10px 20px",
    border: "none",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: "500",
    transition: "all 0.2s"
  },
  buttonPrimary: {
    background: "#667eea",
    color: "white"
  },
  buttonSecondary: {
    background: "#f0f0f0",
    color: "#333"
  },
  runsList: {
    background: "white",
    borderRadius: "12px",
    border: "1px solid #e0e0e0",
    overflow: "hidden"
  },
  runRow: {
    display: "grid",
    gridTemplateColumns: "80px 1fr 120px 100px 100px 120px",
    padding: "15px 20px",
    borderBottom: "1px solid #f0f0f0",
    alignItems: "center"
  },
  runHeader: {
    background: "#f9f9f9",
    fontWeight: "600",
    fontSize: "12px",
    textTransform: "uppercase",
    color: "#666"
  },
  statusBadge: {
    padding: "4px 12px",
    borderRadius: "20px",
    fontSize: "12px",
    fontWeight: "500",
    display: "inline-block"
  },
  statusPassed: { background: "#e8f5e9", color: "#2e7d32" },
  statusFailed: { background: "#ffebee", color: "#c62828" },
  statusRunning: { background: "#e3f2fd", color: "#1565c0" },
  statusQueued: { background: "#fff3e0", color: "#ef6c00" },
  latencyChart: {
    height: "200px",
    background: "#f9f9f9",
    borderRadius: "8px",
    padding: "20px",
    marginTop: "20px",
    display: "flex",
    alignItems: "flex-end",
    gap: "4px"
  },
  latencyBar: {
    background: "linear-gradient(180deg, #667eea 0%, #764ba2 100%)",
    borderRadius: "4px 4px 0 0",
    flex: 1,
    minWidth: "20px"
  },
  modal: {
    position: "fixed",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: "rgba(0,0,0,0.5)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000
  },
  modalContent: {
    background: "white",
    borderRadius: "16px",
    padding: "30px",
    maxWidth: "800px",
    width: "90%",
    maxHeight: "80vh",
    overflow: "auto"
  }
};

// Metric Card Component
function MetricCard({ value, label, color }) {
  const cardStyle = color ? { ...styles.metricCard, background: color } : styles.metricCard;
  return (
    <div style={cardStyle}>
      <div style={styles.metricValue}>{value}</div>
      <div style={styles.metricLabel}>{label}</div>
    </div>
  );
}

// Status Badge Component
function StatusBadge({ status }) {
  const statusStyles = {
    passed: styles.statusPassed,
    completed: styles.statusPassed,
    failed: styles.statusFailed,
    error: styles.statusFailed,
    running: styles.statusRunning,
    queued: styles.statusQueued,
    pending: styles.statusQueued
  };
  
  return (
    <span style={{ ...styles.statusBadge, ...statusStyles[status] || statusStyles.pending }}>
      {status}
    </span>
  );
}

// Latency Distribution Chart
function LatencyChart({ data }) {
  if (!data || data.length === 0) return null;
  
  const maxLatency = Math.max(...data.map(d => d.latency_ms || 0));
  
  return (
    <div style={styles.latencyChart}>
      {data.slice(-20).map((run, i) => (
        <div
          key={i}
          style={{
            ...styles.latencyBar,
            height: `${((run.latency_ms || 0) / maxLatency) * 100}%`,
            opacity: run.status === 'passed' ? 1 : 0.5
          }}
          title={`${run.latency_ms?.toFixed(0) || 0}ms`}
        />
      ))}
    </div>
  );
}

// Run Details Modal
function RunDetailsModal({ run, onClose }) {
  if (!run) return null;
  
  return (
    <div style={styles.modal} onClick={onClose}>
      <div style={styles.modalContent} onClick={e => e.stopPropagation()}>
        <h2>Run #{run.id} Details</h2>
        <StatusBadge status={run.status} />
        
        <div style={{ marginTop: "20px" }}>
          <h3>Metrics</h3>
          <div style={styles.metricsGrid}>
            <MetricCard value={`${run.latency_ms?.toFixed(0) || 0}ms`} label="Latency" color="#4caf50" />
            <MetricCard value={`$${run.cost_usd?.toFixed(4) || 0}`} label="Cost" color="#ff9800" />
          </div>
        </div>
        
        {run.results && (
          <div style={{ marginTop: "20px" }}>
            <h3>Results</h3>
            <pre style={{ 
              background: "#f5f5f5", 
              padding: "15px", 
              borderRadius: "8px",
              overflow: "auto",
              maxHeight: "300px"
            }}>
              {JSON.stringify(run.results, null, 2)}
            </pre>
          </div>
        )}
        
        <button
          style={{ ...styles.button, ...styles.buttonSecondary, marginTop: "20px" }}
          onClick={onClose}
        >
          Close
        </button>
      </div>
    </div>
  );
}

// Main Dashboard Component
export default function Dashboard() {
  const [graphs, setGraphs] = useState([]);
  const [runs, setRuns] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [activeTab, setActiveTab] = useState("graphs");
  const [loading, setLoading] = useState(true);
  const [selectedRun, setSelectedRun] = useState(null);
  const [executingGraphs, setExecutingGraphs] = useState(new Set());
  const [simulationRuns, setSimulationRuns] = useState([]);
  const [simulationLoading, setSimulationLoading] = useState(false);
  const [selectedSimulation, setSelectedSimulation] = useState(null);
  const [simulationEvents, setSimulationEvents] = useState([]);
  const [simulationEvalResult, setSimulationEvalResult] = useState(null);
  const [simulationEvalLoading, setSimulationEvalLoading] = useState(false);
  
  // Fetch data
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [graphsData, runsData, metricsData] = await Promise.all([
        fetchGraphs(),
        fetchRuns(),
        fetchMetrics()
      ]);
      setGraphs(graphsData);
      setRuns(runsData);
      setMetrics(metricsData);
      try {
        const simRuns = await listSimulationRuns();
        setSimulationRuns(simRuns);
      } catch (simError) {
        console.warn("Simulation runs unavailable:", simError);
      }
    } catch (error) {
      console.error("Failed to load data:", error);
    } finally {
      setLoading(false);
    }
  }, []);
  
  useEffect(() => { loadData(); }, [loadData]);

  const loadSimulationRuns = useCallback(async () => {
    setSimulationLoading(true);
    try {
      const runs = await listSimulationRuns();
      setSimulationRuns(runs);
    } catch (error) {
      console.error("Failed to load simulation runs:", error);
    } finally {
      setSimulationLoading(false);
    }
  }, []);

  const loadSimulationDetails = useCallback(async (runId) => {
    setSimulationEvalResult(null);
    try {
      const [run, events] = await Promise.all([
        getSimulationRun(runId),
        getSimulationEvents(runId)
      ]);
      setSelectedSimulation(run);
      setSimulationEvents(events);
    } catch (error) {
      console.error("Failed to load simulation details:", error);
    }
  }, []);

  const runSimulationChecks = useCallback(async (runId) => {
    setSimulationEvalLoading(true);
    setSimulationEvalResult(null);
    try {
      const result = await evaluateSimulationRun(runId, {
        assertions: DEMO_SIMULATION_ASSERTIONS
      });
      setSimulationEvalResult(result);
    } catch (error) {
      console.error("Simulation evaluation failed:", error);
      setSimulationEvalResult({
        passed: false,
        error: error?.message || "Evaluation failed",
        results: []
      });
    } finally {
      setSimulationEvalLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "simulation") {
      loadSimulationRuns();
    }
  }, [activeTab, loadSimulationRuns]);
  
  // Run a graph
  const handleRunGraph = async (graphId) => {
    setExecutingGraphs(prev => new Set([...prev, graphId]));
    try {
      await runGraph(graphId);
      await loadData(); // Refresh data
    } catch (error) {
      console.error("Failed to run graph:", error);
    } finally {
      setExecutingGraphs(prev => {
        const next = new Set(prev);
        next.delete(graphId);
        return next;
      });
    }
  };

  const handleStartSimulation = async () => {
    setSimulationLoading(true);
    try {
      const payload = {
        name: "demo-simulation",
        scenario: "support-escalation",
        steps: 6,
        environment: {
          state: { tickets_open: 3, satisfaction: 0.6 },
          config: {}
        },
        agents: [
          {
            id: "intake_agent",
            type: "support",
            implementation: "llm",
            config: {
              provider: "openai",
              model: "gpt-4o-mini",
              system_prompt: "You are a friendly intake specialist summarising user issues.",
              temperature: 0.3
            }
          },
          {
            id: "resolver_agent",
            type: "expert",
            implementation: "rule",
            config: {
              rules: [
                {
                  name: "resolve_ticket",
                  when: { tickets_open: 3 },
                  action: { type: "increment", payload: { key: "tickets_open", amount: -1 } },
                  messages: [
                    {
                      to: "intake_agent",
                      content: { summary: "Ticket resolved", status: "closed" }
                    }
                  ]
                }
              ]
            }
          }
        ]
      };
      const response = await startSimulationRun(payload);
      await loadSimulationRuns();
      if (response?.run_id) {
        await loadSimulationDetails(response.run_id);
        await runSimulationChecks(response.run_id);
        setActiveTab("simulation");
      }
    } catch (error) {
      console.error("Failed to start simulation run:", error);
    } finally {
      setSimulationLoading(false);
    }
  };
  
  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>🧪 Multi-Agent Behavioral Testing</h1>
        <button
          style={{ ...styles.button, ...styles.buttonPrimary }}
          onClick={loadData}
          disabled={loading}
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>
      
      {/* Metrics Summary */}
      {metrics && (
        <div style={styles.metricsGrid}>
          <MetricCard 
            value={metrics.total_runs || 0} 
            label="Total Runs" 
          />
          <MetricCard 
            value={`${metrics.pass_rate?.toFixed(1) || 0}%`} 
            label="Pass Rate"
            color={metrics.pass_rate > 80 ? "linear-gradient(135deg, #4caf50 0%, #2e7d32 100%)" : 
                   metrics.pass_rate > 50 ? "linear-gradient(135deg, #ff9800 0%, #f57c00 100%)" :
                   "linear-gradient(135deg, #f44336 0%, #c62828 100%)"}
          />
          <MetricCard 
            value={`${metrics.latency_p95?.toFixed(0) || 0}ms`} 
            label="P95 Latency"
            color="linear-gradient(135deg, #2196f3 0%, #1565c0 100%)"
          />
          <MetricCard 
            value={`$${metrics.total_cost_usd?.toFixed(2) || 0}`} 
            label="Total Cost"
            color="linear-gradient(135deg, #9c27b0 0%, #7b1fa2 100%)"
          />
        </div>
      )}
      
      {/* Tabs */}
      <div style={styles.tabs}>
        {["graphs", "runs", "analytics", "simulation"].map(tab => (
          <button
            key={tab}
            style={{
              ...styles.tab,
              ...(activeTab === tab ? styles.tabActive : {})
            }}
            onClick={() => setActiveTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>
      
      {/* Graphs Tab */}
      {activeTab === "graphs" && (
        <div style={styles.graphsGrid}>
          {graphs.map(g => (
            <div 
              key={g.id} 
              style={styles.graphCard}
              onMouseEnter={e => Object.assign(e.currentTarget.style, styles.graphCardHover)}
              onMouseLeave={e => {
                e.currentTarget.style.transform = "none";
                e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.05)";
              }}
            >
              <div style={styles.graphName}>{g.name}</div>
              <div style={styles.graphStats}>
                <span>📦 {g.nodes || 0} nodes</span>
                <span>🔗 {g.edges || 0} edges</span>
                <span>✓ {g.assertions || 0} assertions</span>
              </div>
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  style={{ 
                    ...styles.button, 
                    ...styles.buttonPrimary,
                    opacity: executingGraphs.has(g.id) ? 0.7 : 1
                  }}
                  onClick={() => handleRunGraph(g.id)}
                  disabled={executingGraphs.has(g.id)}
                >
                  {executingGraphs.has(g.id) ? "Running..." : "▶ Run"}
                </button>
                <button style={{ ...styles.button, ...styles.buttonSecondary }}>
                  View
                </button>
              </div>
            </div>
          ))}
          
          {graphs.length === 0 && (
            <div style={{ gridColumn: "1/-1", textAlign: "center", padding: "40px", color: "#666" }}>
              No test graphs found. Upload a YAML graph to get started.
            </div>
          )}
        </div>
      )}
      
      {/* Runs Tab */}
      {activeTab === "runs" && (
        <div style={styles.runsList}>
          <div style={{ ...styles.runRow, ...styles.runHeader }}>
            <div>ID</div>
            <div>Graph</div>
            <div>Status</div>
            <div>Latency</div>
            <div>Cost</div>
            <div>Actions</div>
          </div>
          
          {runs.map(run => (
            <div key={run.id} style={styles.runRow}>
              <div>#{run.id}</div>
              <div>Graph #{run.graph_id}</div>
              <div><StatusBadge status={run.status} /></div>
              <div>{run.latency_ms?.toFixed(0) || 0}ms</div>
              <div>${run.cost_usd?.toFixed(4) || 0}</div>
              <div>
                <button
                  style={{ ...styles.button, ...styles.buttonSecondary, padding: "6px 12px" }}
                  onClick={() => setSelectedRun(run)}
                >
                  Details
                </button>
              </div>
            </div>
          ))}
          
          {runs.length === 0 && (
            <div style={{ padding: "40px", textAlign: "center", color: "#666" }}>
              No runs yet. Execute a test graph to see results.
            </div>
          )}
        </div>
      )}
      
      {/* Analytics Tab */}
      {activeTab === "analytics" && (
        <div>
          <h2 style={{ marginBottom: "20px" }}>Latency Distribution</h2>
          <LatencyChart data={runs} />
          
          <h2 style={{ marginTop: "30px", marginBottom: "20px" }}>Pass/Fail Breakdown</h2>
          <div style={styles.metricsGrid}>
            <MetricCard 
              value={metrics?.passed || 0} 
              label="Passed Runs"
              color="linear-gradient(135deg, #4caf50 0%, #2e7d32 100%)"
            />
            <MetricCard 
              value={metrics?.failed || 0} 
              label="Failed Runs"
              color="linear-gradient(135deg, #f44336 0%, #c62828 100%)"
            />
            <MetricCard 
              value={metrics?.error || 0} 
              label="Error Runs"
              color="linear-gradient(135deg, #ff9800 0%, #f57c00 100%)"
            />
          </div>
        </div>
      )}
      
      {/* Simulation Tab */}
      {activeTab === "simulation" && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px", flexWrap: "wrap", gap: "12px" }}>
            <h2 style={{ margin: 0 }}>Simulation Runs</h2>
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <button
                type="button"
                style={{ ...styles.button, ...styles.buttonSecondary }}
                onClick={() => selectedSimulation && runSimulationChecks(selectedSimulation.id)}
                disabled={simulationEvalLoading || !selectedSimulation}
                title="Re-run preset assertions on the selected run"
              >
                {simulationEvalLoading ? "Checking…" : "Run checks on selected"}
              </button>
              <button
                type="button"
                style={{ ...styles.button, ...styles.buttonPrimary }}
                onClick={handleStartSimulation}
                disabled={simulationLoading}
              >
                {simulationLoading ? "Launching…" : "Start demo + checks"}
              </button>
            </div>
          </div>

          <div style={styles.simulationLayout}>
            <div style={styles.simulationRuns}>
              {simulationRuns.map((run) => {
                const isActive = selectedSimulation?.id === run.id;
                return (
                  <div
                    key={run.id}
                    style={{
                      ...styles.simulationRunItem,
                      ...(isActive ? styles.simulationRunItemActive : {})
                    }}
                    onClick={() => loadSimulationDetails(run.id)}
                  >
                    <div style={{ fontWeight: 600 }}>{run.name}</div>
                    <div style={{ fontSize: "12px", color: "#666" }}>
                      Scenario: {run.scenario} • Status: {run.status}
                    </div>
                    <div style={{ fontSize: "12px", color: "#999", marginTop: "4px" }}>
                      Steps: {run.steps || 0}
                    </div>
                  </div>
                );
              })}
              {simulationRuns.length === 0 && (
                <div style={{ padding: "20px", textAlign: "center", color: "#666" }}>
                  No simulation runs yet. Launch one to explore agent behaviour.
                </div>
              )}
            </div>

            <div style={styles.simulationPanel}>
              {selectedSimulation ? (
                <>
                  <h3 style={{ marginTop: 0 }}>{selectedSimulation.name}</h3>
                  <div style={{ color: "#555", marginBottom: "10px" }}>
                    Scenario: {selectedSimulation.scenario} • Status: {selectedSimulation.status}
                  </div>

                  {simulationEvalResult && (
                    <div
                      style={{
                        marginBottom: "16px",
                        padding: "14px",
                        borderRadius: "10px",
                        border: "1px solid #e0e0e0",
                        background: simulationEvalResult.error
                          ? "#fff5f5"
                          : simulationEvalResult.passed
                            ? "#f0fdf4"
                            : "#fffbeb"
                      }}
                    >
                      <div style={{ fontWeight: 600, marginBottom: "8px", color: "#1a1a1a" }}>
                        {simulationEvalResult.error
                          ? "Evaluation error"
                          : simulationEvalResult.passed
                            ? "Preset checks passed"
                            : "Preset checks failed"}
                      </div>
                      {simulationEvalResult.error && (
                        <div style={{ fontSize: "13px", color: "#b91c1c" }}>{simulationEvalResult.error}</div>
                      )}
                      {(simulationEvalResult.results || []).map((r) => (
                        <div
                          key={r.assertion_id}
                          style={{
                            fontSize: "13px",
                            marginTop: "6px",
                            color: r.passed ? "#166534" : "#9a3412"
                          }}
                        >
                          <strong>{r.assertion_id}</strong> ({r.assertion_type}):{" "}
                          {r.passed ? "ok" : r.message}
                        </div>
                      ))}
                      {simulationEvalResult.events_used != null && (
                        <div style={{ fontSize: "12px", color: "#666", marginTop: "8px" }}>
                          Events used: {simulationEvalResult.events_used}
                        </div>
                      )}
                    </div>
                  )}

                  <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                    {selectedSimulation.agents?.map((agent) => (
                      <div
                        key={agent.agent_id}
                        style={{
                          background: "#f5f5ff",
                          borderRadius: "10px",
                          padding: "12px",
                          flex: "1 1 200px"
                        }}
                      >
                        <div style={{ fontWeight: 600 }}>{agent.agent_id}</div>
                        <div style={{ fontSize: "12px", color: "#555" }}>{agent.agent_type}</div>
                      </div>
                    ))}
                  </div>

                  <div style={{ marginTop: "20px" }}>
                    <h4>Event Timeline</h4>
                    <div style={styles.eventList}>
                      {simulationEvents.map((event) => (
                        <div key={event.id} style={styles.eventItem}>
                          <div style={{ fontSize: "12px", color: "#666" }}>
                            Step {event.step_index} • {event.agent_id || "environment"}
                          </div>
                          <pre
                            style={{
                              background: "#f5f5f5",
                              borderRadius: "8px",
                              padding: "12px",
                              fontSize: "12px",
                              overflow: "auto"
                            }}
                          >
                            {JSON.stringify(event.payload, null, 2)}
                          </pre>
                        </div>
                      ))}
                      {simulationEvents.length === 0 && (
                        <div style={{ padding: "20px", textAlign: "center", color: "#666" }}>
                          No events recorded yet.
                        </div>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <div style={{ padding: "40px", textAlign: "center", color: "#666" }}>
                  Select a simulation run to inspect actions, communications, and resulting state.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Run Details Modal */}
      <RunDetailsModal run={selectedRun} onClose={() => setSelectedRun(null)} />
    </div>
  );
}
