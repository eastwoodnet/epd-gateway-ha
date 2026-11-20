import "./static/js/dithering.js?v=0.4.1";
import { initEpdWorkbench } from "./static/js/app.js?v=0.4.1";

window.EPD_API_PREFIX = "/api/epd_gateway";

class EpdGatewayPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._initialized = false;
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
  }

  get hass() {
    return this._hass;
  }

  async connectedCallback() {
    if (this._initialized) {
      return;
    }
    this._initialized = true;

    const shadow = this.shadowRoot;
    const styleLink = document.createElement("link");
    styleLink.rel = "stylesheet";
    styleLink.href = "/epd_gateway_static/static/css/style.css?v=0.4.0";

    const container = document.createElement("div");
    container.className = "epd-body";

    try {
      const resp = await fetch("/epd_gateway_static/templates/index.html?v=0.4.0");
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const htmlText = await resp.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(htmlText, "text/html");
      while (doc.body.firstChild) {
        container.appendChild(document.adoptNode(doc.body.firstChild));
      }
    } catch (err) {
      const errBox = document.createElement("div");
      errBox.style.padding = "24px";
      errBox.style.color = "#dc2626";
      errBox.textContent = `加载 EPD 工作台界面失败: ${err.message}`;
      container.appendChild(errBox);
      shadow.append(styleLink, container);
      return;
    }

    shadow.append(styleLink, container);
    initEpdWorkbench(shadow, () => this._hass, this);
  }
}

if (!customElements.get("epd-gateway-panel")) {
  customElements.define("epd-gateway-panel", EpdGatewayPanel);
}
