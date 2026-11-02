"use client";

import { useEffect, useRef, useState } from "react";

interface Toast {
  id: number;
  message: string;
  type: "success" | "error" | "info";
}

let addToastGlobal: ((msg: string, type: Toast["type"]) => void) | null = null;

export function toast(message: string, type: Toast["type"] = "info") {
  addToastGlobal?.(message, type);
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  useEffect(() => {
    addToastGlobal = (message, type) => {
      const id = ++counter.current;
      setToasts((prev) => [...prev, { id, message, type }]);
      setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3500);
    };
    return () => { addToastGlobal = null; };
  }, []);

  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.type}`}>
          {t.message}
        </div>
      ))}
    </div>
  );
}
