import { css } from "lit";
export const cardStyles = css`
  :host {
    display: block;
    min-width: 0;
    container-type: inline-size;
    color: var(--primary-text-color);
  }
  * {
    box-sizing: border-box;
  }
  ha-card {
    overflow: hidden;
    height: 100%;
    background: var(--ha-card-background, var(--card-background-color));
    border-radius: var(--ha-card-border-radius, 12px);
    font-family: var(--ha-font-family-body, inherit);
  }
  header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 20px 20px 12px;
  }
  header > .icon {
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    flex-shrink: 0;
    border-radius: 50%;
    color: var(--primary-color);
    background: var(--secondary-background-color);
  }
  .headings {
    min-width: 0;
    flex: 1;
  }
  h2 {
    margin: 0;
    font-size: var(--ha-font-size-xl, 20px);
    font-weight: var(--ha-font-weight-medium, 500);
    line-height: 1.4;
    overflow-wrap: anywhere;
  }
  h3 {
    margin: 0 0 8px;
    font-size: 1rem;
  }
  .subtitle,
  .secondary {
    color: var(--secondary-text-color);
    font-size: 0.875rem;
    line-height: 1.5;
  }
  .content {
    padding: 4px 20px 20px;
  }
  .state {
    padding: 20px 0;
    display: flex;
    gap: 12px;
    align-items: center;
    line-height: 1.5;
  }
  .state ha-icon {
    color: var(--secondary-text-color);
    flex-shrink: 0;
  }
  button {
    font: inherit;
    color: inherit;
    background: transparent;
    border: 0;
    cursor: pointer;
    min-height: 44px;
    border-radius: 8px;
  }
  .icon-button {
    width: 44px;
    display: grid;
    place-items: center;
    flex-shrink: 0;
    color: var(--secondary-text-color);
  }
  button:hover,
  summary:hover {
    background: var(--secondary-background-color);
  }
  :is(button, summary, a):focus-visible {
    outline: 3px solid var(--primary-color);
    outline-offset: 2px;
  }
  ha-icon {
    width: 22px;
    height: 22px;
    display: inline-flex;
    vertical-align: middle;
  }
  .timing {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    gap: 12px;
    align-items: center;
    margin: 12px 0 16px;
  }
  .timing .time {
    font-size: clamp(1.5rem, 7cqi, 2.25rem);
    font-weight: 600;
    letter-spacing: -0.025em;
    line-height: 1.3;
  }
  .timing .destination {
    text-align: end;
  }
  .stop-name {
    font-weight: 500;
    margin-top: 6px;
    overflow-wrap: anywhere;
    line-height: 1.4;
  }
  .chip {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    padding: 6px 10px;
    border-radius: 10px;
    font-size: 0.875rem;
    font-weight: 500;
    max-width: 100%;
    overflow-wrap: anywhere;
  }
  .chip ha-icon {
    flex-shrink: 0;
  }
  .status {
    display: flex;
    gap: 8px;
    align-items: center;
    margin: 12px 0;
    font-size: 0.875rem;
  }
  .metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 16px;
    margin: 12px 0 16px;
    color: var(--secondary-text-color);
    font-size: 0.875rem;
  }
  .metric {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .alert-strip {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    background: color-mix(
      in srgb,
      var(--warning-color) 14%,
      var(--card-background-color)
    );
    border-radius: 10px;
    margin: 12px 0;
    font-size: 0.875rem;
  }
  .alert-strip ha-icon {
    color: var(--warning-color);
  }
  .disclosure {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-top: 1px solid var(--divider-color);
    border-radius: 0;
    padding: 12px 0;
    text-align: start;
    margin-top: 12px;
  }
  .legs,
  .departures,
  .alerts,
  .calling-stops {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .leg {
    border-inline-start: 3px solid var(--primary-color);
    padding: 4px 0 12px 16px;
    margin: 8px 0 0 4px;
  }
  .endpoint,
  .call {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: baseline;
    margin: 10px 0;
  }
  .endpoint > div,
  .call > div {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .endpoint time,
  .call time {
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
  }
  .endpoint .label {
    font-weight: 500;
  }
  .call {
    position: relative;
    padding-inline-start: 12px;
    font-size: 0.875rem;
  }
  .call::before {
    content: "";
    position: absolute;
    inset-inline-start: -5px;
    top: 6px;
    width: 9px;
    height: 9px;
    border: 2px solid var(--primary-color);
    border-radius: 50%;
    background: var(--card-background-color);
  }
  .calling-stops {
    border-inline-start: 2px solid var(--primary-color);
    margin-inline-start: 4px;
  }
  .call .prediction {
    color: var(--secondary-text-color);
    display: block;
    font-size: 0.8rem;
  }
  details {
    margin-top: 12px;
  }
  summary {
    cursor: pointer;
    min-height: 44px;
    padding: 12px 4px;
    border-radius: 8px;
    font-size: 0.875rem;
  }
  .departure {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px;
    padding: 16px 0;
    border-bottom: 1px solid var(--divider-color);
  }
  .departure:last-child,
  .alert:last-child {
    border-bottom: 0;
  }
  .departure .destination-name {
    margin-top: 8px;
    overflow-wrap: anywhere;
  }
  .departure .when {
    text-align: end;
    white-space: nowrap;
    font-size: 1.125rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .departure .when .secondary {
    font-weight: 400;
    margin-top: 4px;
  }
  .alert {
    padding: 16px 0;
    border-bottom: 1px solid var(--divider-color);
  }
  .alert-title {
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }
  .alert-title ha-icon {
    color: var(--warning-color);
    flex-shrink: 0;
  }
  .description {
    white-space: pre-line;
    overflow-wrap: anywhere;
    line-height: 1.6;
    font-size: 0.875rem;
  }
  .note {
    margin-top: 12px;
    color: var(--secondary-text-color);
    font-size: 0.8rem;
    line-height: 1.5;
  }
  @container (max-width: 340px) {
    header {
      padding: 16px 16px 8px;
      gap: 8px;
    }
    .content {
      padding: 4px 16px 16px;
    }
    .timing {
      gap: 6px;
    }
    .endpoint,
    .call {
      gap: 8px;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    *,
    *::before {
      animation: none !important;
      transition: none !important;
    }
  }
`;
