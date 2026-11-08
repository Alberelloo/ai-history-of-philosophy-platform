import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Шрифты отдаёт сам сайт из пакетов @fontsource: Onest для интерфейса, Literata для чтения.
import "@fontsource/onest/400.css";
import "@fontsource/onest/500.css";
import "@fontsource/onest/600.css";
import "@fontsource/onest/700.css";
import "@fontsource-variable/literata/opsz.css";
import "@fontsource-variable/literata/opsz-italic.css";
import "./styles/tokens.css";
import "./styles/components.css";
import "./styles.css";
import "./styles/card.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
