export interface EntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
  last_updated?: string;
}
export interface VehicleTrackerAttributes {
  active_leg_index?: number | null;
  route_name?: string | null;
  route_code?: string | null;
  vehicle_type?: string | null;
  vehicle_label?: string | null;
  position_status?:
    | "live"
    | "stale"
    | "ambiguous"
    | "no_position"
    | "no_active_leg"
    | "disabled";
  position_timestamp?: string | null;
}
export interface RegistryEntry {
  entity_id: string;
  platform?: string;
  translation_key?: string;
  device_id?: string;
}
export interface HomeAssistant {
  states: Record<string, EntityState>;
  entities?: Record<string, RegistryEntry>;
  devices?: Record<string, { name?: string; name_by_user?: string }>;
  locale?: { language?: string; time_format?: string; time_zone?: string };
  language?: string;
  config?: { time_zone?: string };
}
export interface CardConfig {
  type: string;
  entity?: string;
  title?: string;
  show_fare?: boolean;
  legs_expanded?: boolean;
  show_disruptions?: boolean;
  show_platform?: boolean;
  max_departures?: number;
  max_alerts?: number;
}
export type Row = Record<string, unknown>;
export interface Departure {
  tripId?: string;
  time?: string;
  route: string;
  vehicle: string;
  headsign?: string;
  platform?: string;
  color?: string;
}
