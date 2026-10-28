export type Helix2Options = {Int8?:string; WaveSize?:string; NetworkResolution?:string; UseReactiveMask?:string};
export type Helix2State = {
  state:"helix2"|"stock"|"blocked"; managed:boolean; enabled?:boolean; running:boolean;
  can_modify:boolean; actions:string[]; options:Helix2Options; reason?:string;
};
export const helix2Labels:Record<string,string> = {
  adopt:"Manage this installation", install:"Install HelixSR 2.0", enable:"Enable HelixSR",
  disable:"Use original FSR", remove:"Remove management and use original FSR",
  settings:"Save settings", recover:"Recover interrupted change",
};
export function availableActions(state?:Helix2State):string[] {
  if (!state || state.running || !state.can_modify) return [];
  return state.actions.filter(action=>Object.prototype.hasOwnProperty.call(helix2Labels,action));
}
export function changedOptions(before:Helix2Options, after:Helix2Options):Helix2Options {
  const result:Helix2Options={};
  for (const key of ["Int8","WaveSize","NetworkResolution","UseReactiveMask"] as const) {
    if (after[key]!==undefined && after[key]!==before[key]) result[key]=after[key];
  }
  return result;
}
