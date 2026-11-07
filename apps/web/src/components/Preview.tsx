import React from "react";
import { FileItem } from "../types/archive";

export function Preview({ item }: { item: FileItem }) {
  if (item.color === "room")
    return (
      <div className="roomscene">
        <div className="window" />
        <div className="arch" />
        <div className="table" />
        <div className="vase" />
      </div>
    );
  if (item.color === "forest")
    return (
      <div className="forestscene">
        {[0, 1, 2, 3, 4, 5, 6].map((i) => (
          <i
            key={i}
            style={{ left: `${i * 16 - 5}%`, height: `${100 + (i % 3) * 20}%` }}
          />
        ))}
      </div>
    );
  if (item.color === "social")
    return (
      <div className="socialsheet">
        <small>یادداشت‌های یک ذهن کنجکاو</small>
        <b>
          کمتر بخوان،
          <br />
          عمیق‌تر یاد بگیر.
        </b>
        <span>هر روز، یک قدم کوچک</span>
      </div>
    );
  return (
    <div className="document">
      <small>
        {item.color === "report" ? "پژوهش و فناوری" : "دفتر یادداشت‌ها"}
      </small>
      <strong>{item.title}</strong>
      <div className="doclines">
        {[1, 2, 3, 4, 5].map((n) => (
          <i key={n} style={{ width: `${90 - (n % 3) * 12}%` }} />
        ))}
      </div>
      <span className="docseal">{item.color === "notes" ? "✎" : "ساهر"}</span>
    </div>
  );
}
