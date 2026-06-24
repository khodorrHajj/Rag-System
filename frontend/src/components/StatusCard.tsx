type StatusCardProps = {
  title: string;
  value: string;
  tone?: "default" | "success" | "warning";
};

export function StatusCard({ title, value, tone = "default" }: StatusCardProps) {
  return (
    <section className={`status-card status-card--${tone}`}>
      <p className="status-card__label">{title}</p>
      <p className="status-card__value">{value}</p>
    </section>
  );
}

