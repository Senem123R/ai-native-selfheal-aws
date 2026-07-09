import { useState, useEffect } from "react"

const API = "https://a5dv13ptvc.execute-api.us-east-1.amazonaws.com/Prod"
const API2 = "https://a5dv13ptvc.execute-api.us-east-1.amazonaws.com/Prod"

const SEV_BG = {CRITICAL:"#FCEBEB", HIGH:"#FAEEDA", MEDIUM:"#FFF8E1", LOW:"#EAF3DE"}
const SEV_TX = {CRITICAL:"#A32D2D", HIGH:"#854F0B", MEDIUM:"#5D4037", LOW:"#3B6D11"}

export default function App() {
  const [incidents, setIncidents] = useState([])
  const [status, setStatus] = useState("Loading...")
  const [loading, setLoading] = useState(false)

  const runObserveAndFetch = async () => {
    setLoading(true)
    setStatus("Checking all services...")

    try {
      // Step 1: Trigger OBSERVE to scan for new errors
      const observeRes = await fetch(API2 + "/observe", {method:"POST"})
      const observeData = await observeRes.json()
      const count = observeData.incidents_found || 0

      // Step 2: Fetch ALL incidents from DynamoDB
      const incRes = await fetch(API2 + "/incidents")
      
      if (incRes.ok) {
        const incData = await incRes.json()
        setIncidents(incData.incidents || [])
      }

      setStatus(
        `Last checked: ${new Date().toLocaleTimeString()} — ${count} new incidents found`
      )

    } catch(e) {
      console.log("Error:", e)
      setStatus("Error connecting to API")
    }

    setLoading(false)
  }

  useEffect(() => {
    runObserveAndFetch()
    const t = setInterval(runObserveAndFetch, 60000)
    return () => clearInterval(t)
  }, [])

  return (
    <div style={{maxWidth:700, margin:"0 auto", padding:"2rem 1rem", fontFamily:"system-ui"}}>

      {/* Header */}
      <h1 style={{fontSize:22, fontWeight:500, marginBottom:4}}>
        🛒 E-Commerce Self-Healing Dashboard
      </h1>
      <p style={{color:"#888", fontSize:13, marginBottom:20}}>
        AWS Lambda · DynamoDB · CloudWatch · OpenRouter AI
      </p>

      {/* OODA Pills */}
      <div style={{display:"flex", gap:8, marginBottom:20, flexWrap:"wrap"}}>
        {["✅ OBSERVE","✅ ANALYZE","✅ DECIDE","✅ ACT"].map(p=>(
          <span key={p} style={{
            background:"#EAF3DE", color:"#3B6D11",
            padding:"4px 12px", borderRadius:999, fontSize:12
          }}>{p}</span>
        ))}
      </div>

      {/* Service Cards */}
      <div style={{display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:8, marginBottom:20}}>
        {["auth","payments","products","cart","orders","tracking"].map(s=>(
          <div key={s} style={{background:"#EAF3DE", borderRadius:8, padding:"10px 12px"}}>
            <div style={{fontSize:11, color:"#3B6D11"}}>{s}-service</div>
            <div style={{fontSize:13, color:"#27500A", fontWeight:500}}>● healthy</div>
          </div>
        ))}
      </div>

      {/* Controls */}
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:16}}>
        <span style={{fontSize:13, color:"#888"}}>{status}</span>
        <button
          onClick={runObserveAndFetch}
          disabled={loading}
          style={{
            padding:"7px 16px", borderRadius:6,
            border:"1px solid #ddd",
            background: loading ? "#f5f5f5" : "white",
            cursor: loading ? "not-allowed" : "pointer",
            fontSize:13
          }}>
          {loading ? "Checking..." : "Check now"}
        </button>
      </div>

      {/* Incident count badge */}
      <div style={{fontSize:14, fontWeight:500, marginBottom:10, color:"#333"}}>
        Incidents
        {incidents.length > 0 && (
          <span style={{
            background:"#FCEBEB", color:"#A32D2D",
            padding:"2px 8px", borderRadius:999,
            fontSize:12, marginLeft:8
          }}>
            {incidents.length}
          </span>
        )}
      </div>

      {/* Incident list */}
      {incidents.length === 0 ? (
        <div style={{
          textAlign:"center", padding:40, color:"#888",
          border:"1px dashed #ddd", borderRadius:8
        }}>
          No incidents detected — all services healthy ✅
        </div>
      ) : (
        incidents.map((inc, idx) => (
          <div key={inc.id || idx} style={{
            background: SEV_BG[inc.severity] || "#fff",
            border: `1px solid ${SEV_TX[inc.severity] || "#ddd"}`,
            borderRadius:8, padding:"14px 16px", marginBottom:10
          }}>

            {/* Title and severity */}
            <div style={{display:"flex", justifyContent:"space-between", marginBottom:6}}>
              <b style={{fontSize:14}}>{inc.title}</b>
              <span style={{
                color: SEV_TX[inc.severity],
                background: SEV_BG[inc.severity],
                border: `1px solid ${SEV_TX[inc.severity]}`,
                padding:"2px 8px", borderRadius:4, fontSize:11, fontWeight:500
              }}>
                {inc.severity}
              </span>
            </div>

            {/* Service and time */}
            <div style={{fontSize:12, color:"#888", marginBottom:8}}>
              {inc.service_name} · {inc.timestamp}
            </div>

            {/* Description */}
            <div style={{fontSize:12, color:"#555", marginBottom:8}}>
              {inc.description}
            </div>

            {/* Error count */}
            <div style={{fontSize:12, color:"#888"}}>
              Errors detected: <b>{inc.error_count}</b>
            </div>

          </div>
        ))
      )}
    </div>
  )
}