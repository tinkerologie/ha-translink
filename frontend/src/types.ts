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
  callService?(
    domain: string,
    service: string,
    serviceData: Record<string, unknown>,
    target: undefined,
    notifyOnError: boolean,
    returnResponse: true,
  ): Promise<{ response: JourneyAlternatives }>;
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
  show_arrivals?: boolean;
  show_filters?: boolean;
  max_departures?: number;
  max_alerts?: number;
  show_planner?: boolean;
  alternatives_limit?: number;
}
export type Row = Record<string, unknown>;
export interface Departure {
  tripId?: string;
  visitId?: string;
  time?: string;
  expectedTime?: string;
  timeSource?: "scheduled" | "realtime";
  cancelled?: boolean;
  skipped?: boolean;
  extra?: boolean;
  platformChange?: {
    platform?: string;
    oldPlatform?: string;
    isSource?: boolean;
  };
  boarding?: string;
  route: string;
  routeId?: string;
  direction?: string;
  vehicle: string;
  headsign?: string;
  platform?: string;
  color?: string;
}

export type BoardView = "departures" | "arrivals";
export type BoardOrder = "scheduled" | "route";
export interface BoardFilterOption {
  value: string;
  label: string;
}

export type JourneySort = "departure" | "arrival" | "duration";

export interface JourneyAlternative {
  planner_index: number;
  planner_first: boolean;
  departure: string | null;
  arrival: string | null;
  duration_mins: number | null;
  transfers: number | null;
  legs: Array<{
    mode: string;
    route_code: string | null;
    route_name: string | null;
    headsign: string | null;
    origin: string | null;
    destination: string | null;
    departure: string | null;
    arrival: string | null;
  }>;
  legs_truncated: boolean;
  notices: PlannerNotice[];
}

export interface PlannerNotice {
  id: number | string;
  title: string | null;
}

export interface JourneyAlternatives {
  sort_by: JourneySort;
  total_alternatives: number;
  returned: number;
  truncated: boolean;
  alternatives: JourneyAlternative[];
  plan_notices: PlannerNotice[];
}
