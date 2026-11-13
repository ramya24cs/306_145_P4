import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api.js";
import { ErrorBox, PageHeader, Skeleton, StatCard, useLoad } from "../ui.jsx";

const BLUES = ["#0a2a63", "#1d6fe8", "#19c2d8", "#8dbbe9", "#c4dcf4"];
const CAT_COLORS = { Critical: "#e5484d", Stat: "#e8940c", Routine: "#1d6fe8", Pending: "#6a4cc7", Error: "#5b6b7f" };

function Box({ title, children }) {
  return <section className="card"><h3>{title}</h3><div className="chart-box">{children}</div></section>;
}

export default function Analytics() {
  const { data, loading, error, reload } = useLoad(() => api.analytics(), [], 8000);
  if (loading && !data) return <Skeleton n={4} />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const s = data.summary;

  return (
    <>
      <PageHeader title="Analytics" sub="Charts redraw the moment a report is submitted, assigned or resolved." />
      <div className="stats">
        <StatCard label="Total reports" value={s.total} />
        <StatCard label="Resolved" value={s.resolved} tone="ok" />
        <StatCard label="Unresolved" value={s.unresolved} tone="warn" />
        <StatCard label="Waiting" value={s.waiting} />
        <StatCard label="Escalated" value={s.escalated} tone={s.escalated ? "bad" : ""} />
        <StatCard label="SLA breached" value={s.sla_breached} tone={s.sla_breached ? "bad" : "ok"} />
        <StatCard label="Avg. minutes to assign" value={s.avg_assignment_minutes ?? "-"} />
      </div>
      <div className="grid g2">
        <Box title="Zone-wise report distribution">
          <ResponsiveContainer><BarChart data={data.zone_distribution}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis allowDecimals={false} /><Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #e0e8f4" }} />
            <Bar dataKey="value" name="Reports" fill="#1d6fe8" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
        </Box>
        <Box title="Category-wise report distribution">
          <ResponsiveContainer><PieChart><Pie data={data.category_distribution.filter((c) => c.value > 0)} dataKey="value" nameKey="name" outerRadius={95} label={(e) => `${e.name} ${e.value}`}>
            {data.category_distribution.filter((c) => c.value > 0).map((c) => <Cell key={c.name} fill={CAT_COLORS[c.name]} />)}</Pie><Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #e0e8f4" }} /><Legend /></PieChart></ResponsiveContainer>
        </Box>
        <Box title="Resolved versus unresolved">
          <ResponsiveContainer><PieChart><Pie data={data.resolution} dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} label={(e) => `${e.name} ${e.value}`}>
            <Cell fill="#16a06c" /><Cell fill="#e8940c" /></Pie><Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #e0e8f4" }} /><Legend /></PieChart></ResponsiveContainer>
        </Box>
        <Box title="Priority-wise report distribution">
          <ResponsiveContainer><BarChart data={data.priority_distribution} layout="vertical" margin={{ left: 30 }}><CartesianGrid strokeDasharray="3 3" /><XAxis type="number" allowDecimals={false} /><YAxis type="category" dataKey="name" width={120} /><Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #e0e8f4" }} />
            <Bar dataKey="value" name="Reports" radius={[0, 4, 4, 0]}>{data.priority_distribution.map((_, i) => <Cell key={i} fill={BLUES[i]} />)}</Bar></BarChart></ResponsiveContainer>
        </Box>
      </div>
      <Box title="Doctor-wise workload (active load vs. maximum capacity)">
        <ResponsiveContainer><BarChart data={data.doctor_workload}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis allowDecimals={false} /><Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #e0e8f4" }} /><Legend />
          <Bar dataKey="load" name="Active load" fill="#1d6fe8" radius={[4, 4, 0, 0]} /><Bar dataKey="capacity" name="Max capacity" fill="#c4dcf4" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
      </Box>
    </>
  );
}
