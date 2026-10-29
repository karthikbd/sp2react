import type { Api } from "../api";
import type { Ctx, RuleError } from "../runtime/rules";
import type { Values } from "../runtime/spec";

// Contract for agent-written behaviour that spec rules cannot express (rule kind "custom").
export interface Handler {
  onLoad?: (ctx: Ctx, api: Api) => void;
  onChange?: (field: string, ctx: Ctx) => Values | void;
  validate?: (ctx: Ctx) => RuleError[];
}
