import { useState, useEffect } from "react"

// Paste your SAM API Gateway URL here after deploying
const API = "https://a5dv13ptvc.execute-api.us-east-1.amazonaws.com/Prod"

const SEV_BG = { CRITICAL: "#FCEBEB", HIGH: "#FAEEDA", MEDIUM: "#FAEEDA", LOW: "#EAF3DE" }
const SEV_TX = { CRITICAL: "#A32D2D", HIGH: "#854F0B", MEDIUM: "#854F0B", LOW: "#3B6D11" }

const SERVICES = ["auth", "payments", "products", "cart", "orders", "tracking"]

export default function App() {
  const [incidents, setIncidents] = useState([])
  const [status, setStatus] = useState("Loading...")
  const [serviceHealth, setServiceHealth] = useState(
    Object.fromEntries(SERVICES.map(s => [s, "healthy"]))
  )

  const runObserve = async () => {
    setStatus("Checking all services...")
    try {
      const res = await fetch(API + "/observe", { method: "POST" })
      const data = await res.json()
      setIncidents(data.incidents || [])
      setStatus(`Last checked: ${new Date().toLocaleTimeString()} — ${data.incidents_found ?? 0} incidents found`)

      const updated = { ...serviceHealth }
      if (data.incidents) {
        data.incidents.forEach(i => {
          if (i.service_name) updated[i.service_name] = i.severity?.toLowerCase() || "error"
        })
      }
      setServiceHealth(updated)
    } catch (e) {
      setStatus("Error connecting to API")
    }
  }

  useEffect(() => {
    runObserve()
    const t = setInterval(runObserve, 60000)
    return () => clearInterval(t)
  }, [])

  const getBg = (health) => {
    if (health === "healthy") return "#EAF3DE"
    if (health === "critical") return "#FCEBEB"
    return "#FAEEDA"
  }

  const getTx = (health) => {
    if (health === "healthy") return "#27500A"
    if (health === "critical") return "#A32D2D"
    return "#854F0B"
  }

  return (
    <div style={{ maxWidth: 700, margin: "0 auto", padding: "2rem 1rem", fontFamily: "system-ui" }}>
      <h1 style={{ fontSize: 22, fontWeight: 500, marginBottom: 4 }}>
        E-Commerce Self-Healing Dashboard
      </h1>
      <p style={{ color: "#666", fontSize: 13, marginBottom: 24 }}>
        AWS Lambda · DynamoDB · CloudWatch · Bedrock Claude
      </p>

      {/* Service Health Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginBottom: 24 }}>
        {SERVICES.map(s => (
          <div key={s} style={{ background: getBg(serviceHealth[s]), borderRadius: 8, padding: "8px 12px" }}>
            <div style={{ fontSize: 11, color: getTx(serviceHealth[s]) }}>{s}</div>
            <div style={{ fontSize: 12, color: getTx(serviceHealth[s]), fontWeight: 500 }}>
              {serviceHealth[s]}
            </div>
          </div>
        ))}
      </div>

      {/* Status bar */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16, alignItems: "center" }}>
        <span style={{ fontSize: 13, color: "#888" }}>{status}</span>
        <button onClick={runObserve}
          style={{ padding: "6px 14px", borderRadius: 6, border: "1px solid #ddd",
            background: "white", cursor: "pointer", fontSize: 13 }}>
          Check now
        </button>
      </div>

      {/* Incidents */}
      {incidents.length === 0 && (
        <div style={{ textAlign: "center", padding: 40, color: "#888",
          border: "1px dashed #ddd", borderRadius: 8 }}>
          No incidents — all 6 services running fine ✓
        </div>
      )}
      {incidents.map((i, idx) => (
        <div key={i.id || idx} style={{
          background: SEV_BG[i.severity] || "#f9f9f9",
          border: `1px solid ${SEV_TX[i.severity] || "#ccc"}`,
          borderRadius: 8, padding: "12px 16px", marginBottom: 10
        }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <b style={{ fontSize: 14 }}>{i.title}</b>
            <span style={{ color: SEV_TX[i.severity], fontSize: 12, fontWeight: 500 }}>
              {i.severity}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>
            {i.service_name} · {i.timestamp}
          </div>
          {i.root_cause && (
            <div style={{ fontSize: 12, color: "#555", marginTop: 6, fontStyle: "italic" }}>
              Claude: {i.root_cause}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}