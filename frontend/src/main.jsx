import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { LiveProvider, ToastProvider } from "./ui.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ToastProvider>
      <LiveProvider>
        <App />
      </LiveProvider>
    </ToastProvider>
  </React.StrictMode>
);
