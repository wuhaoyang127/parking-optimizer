export function FacilityLegend() {
  const items = [
    ["available", "空闲"], ["occupied", "占用"], ["unavailable", "不可用"],
    ["unknown", "未知"], ["charging", "充电"], ["tandem", "纵深组"], ["buffer", "缓冲位"],
  ] as const;
  return <div className="facility-legend" aria-label="布局图例">{items.map(([kind, label]) => <span key={kind}><i className={kind} />{label}</span>)}</div>;
}
