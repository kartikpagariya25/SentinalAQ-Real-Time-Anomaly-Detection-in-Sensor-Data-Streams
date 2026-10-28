import { GraduationCap, Mail, Building2 } from "lucide-react";
import { Card } from "./Shared";

const TEAM = [
  { name: "Kartik Pagariya", tag: "ML pipeline & full-stack", initials: "KP" },
  { name: "Aditya Dengale", tag: "Detection & features", initials: "AD" },
  { name: "Vikrant Kadam", tag: "Data & evaluation", initials: "VK" },
  { name: "Pranali Yelavikar", tag: "Analysis & reporting", initials: "PY" },
];

function Avatar({ initials }) {
  return (
    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-brandpale text-sm font-bold text-brand ring-1 ring-red-100">
      {initials}
    </div>
  );
}

export default function TeamView() {
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-start gap-3">
          <GraduationCap className="mt-0.5 text-brand" size={22} />
          <div>
            <h3 className="text-base font-semibold text-ink">Project team</h3>
            <p className="mt-1 text-sm text-muted">
              A four-member student team at Vishwakarma Institute of Technology (VIT), Pune — Artificial Intelligence & Data Science. SentinelAQ is their sponsored industry project for Respirer Living Sciences.
            </p>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {TEAM.map((m) => (
          <Card key={m.name}>
            <div className="flex items-center gap-3">
              <Avatar initials={m.initials} />
              <div>
                <div className="font-semibold text-ink">{m.name}</div>
                <div className="text-sm text-muted">{m.tag}</div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card title="Sponsor">
        <div className="space-y-2 text-sm text-ink/80">
          <p className="flex items-center gap-2"><Building2 size={15} className="text-brand" /> Respirer Living Sciences</p>
          <p className="flex items-center gap-2"><Mail size={15} className="text-brand" /> Sponsor contact: Kevin Joshi</p>
        </div>
      </Card>
    </div>
  );
}
