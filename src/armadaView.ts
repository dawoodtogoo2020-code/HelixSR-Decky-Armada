export type Action = "install"|"adopt"|"update"|"enable"|"disable"|"remove"|"recover";
export type Selection = {executable?:string; dx12:boolean};
export type Source = {ready:boolean; reason?:string; source?:string};
export type Game = {
  id:string; name:string; folder:string; appid?:string; route:string|null;
  compatibility:string; reasons:string[]; managed:boolean; enabled:boolean; legacy:boolean;
  dx12_detected?:boolean; renderer_unsupported?:boolean; recovery_available?:boolean;
  dx12_confirmation_needed?:boolean; executable_selection_needed?:boolean; awareness_deferred?:boolean;
  executable_choices?:{path:string;dx12:boolean}[];
  selected_executable?:string; main_exe?:string; target?:string; installed_version?:string;
  installed_model?:string; helix_runtime?:string; framegen_summary?:string; gameplay_warning?:string;
  logs?:{path:string;excerpt?:string;modified?:number}[];
  installation_status?:{running:boolean;can_modify?:boolean;can_restore?:boolean;state?:string;label?:string;summary?:string;
    issues?:{code:string;title:string;reason:string;steps:string[];blocking:boolean}[]};
};
export function isDx12Candidate(game:Game):boolean {
  const appid=Number(game.appid);
  const blockers=game.installation_status?.issues?.filter(issue=>issue.blocking)||[];
  const selectableBlock=game.compatibility==="blocked" && blockers.length>0 &&
    blockers.every(issue=>issue.code==="game_running"||issue.code==="executable_selection");
  // Keep an existing, evidenced DX12 installation reachable for review even
  // when its files need attention. Action permissions are evaluated separately.
  const managedReview=game.managed && game.compatibility!=="unsupported";
  return typeof game.appid==="string" && /^\d+$/.test(game.appid) && Number.isSafeInteger(appid) && appid>0 && appid<=4294967295 &&
    game.dx12_detected===true && (game.compatibility==="candidate"||selectableBlock||managedReview) &&
    (game.route==="direct" || game.route==="optiscaler") && !game.renderer_unsupported;
}
export function eligibleGames(games:Game[]):Game[] {
  return games.filter(isDx12Candidate).sort((a,b)=>a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
}
export function managedGames(games:Game[]):Game[] {
  return games.filter(game=>game.managed||game.legacy||game.recovery_available);
}
export function selectInitialGame(games:Game[],preferred?:string):string {
  const eligible=eligibleGames(games);
  return (eligible.find(game=>game.id===preferred)||eligible.find(game=>game.installation_status?.running)||
    eligible.find(game=>game.managed)||eligible[0])?.id||"";
}
export function statusArguments(game:Game,executable?:string):[string,string?] {
  return !game.managed && game.route==="optiscaler" && executable && game.executable_choices?.some(choice=>choice.path===executable)
    ? [game.id,executable] : [game.id];
}
export function viewGame(game:Game|undefined,source:Source|undefined,selection:Selection) {
  const view:{title:string;detail:string;nextStep:string;color:string;primary:{action:Action;label:string;enabled:boolean}|null;
    toggle:{checked:boolean;enabled:boolean}|null;canRemove:boolean;canRecover:boolean;needsExecutable:boolean;needsDx12:boolean;routeLabel:string}={
    title:"Loading game status",detail:"Wait for the library scan.",nextStep:"Refresh when scanning finishes.",color:"#9ca3af",
    primary:null,toggle:null,canRemove:false,canRecover:false,needsExecutable:false,needsDx12:false,routeLabel:"Unavailable"};
  if (!game) return view;
  const status=game.installation_status;
  const running=status?.running===true;
  const candidate=isDx12Candidate(game);
  const canRestore=status?.can_restore===true;
  const blocking=status?.issues?.find(issue=>issue.blocking);
  view.routeLabel=game.route==="direct"?"Direct FSR":game.route==="optiscaler"?"OptiScaler proxy":"Unavailable";
  view.needsExecutable=!game.managed && game.route==="optiscaler" && game.executable_selection_needed===true;
  view.needsDx12=game.dx12_confirmation_needed===true;
  view.canRemove=!running && canRestore && (game.managed||game.legacy);
  view.canRecover=!running && game.recovery_available===true;
  const selected=selection.executable||game.selected_executable;
  // The backend exposes only scanned x64 PE choices. Their renderer imports
  // may load dynamically; explicit confirmation complements independent game evidence.
  const executableReady=!view.needsExecutable || !!game.executable_choices?.some(choice=>choice.path===selected && (choice.dx12||selection.dx12));
  const ready=candidate && game.compatibility==="candidate" && source?.ready===true && status?.can_modify===true && !blocking && executableReady && (!view.needsDx12||selection.dx12);
  const action:Action=game.legacy?"adopt":!game.managed?"install":game.enabled?"disable":"enable";
  const labels={adopt:"Adopt installation",install:"Install HelixSR",enable:"Enable HelixSR",disable:"Use original",remove:"Remove installation",recover:"Recover installation",update:"Update installation"};
  view.primary={action,label:labels[action],enabled:action==="disable"?canRestore:ready};
  if(game.managed) view.toggle={checked:game.enabled,enabled:game.enabled?canRestore:ready};
  view.title=game.enabled?"HelixSR enabled":game.managed?"Original game selected":game.legacy?"Existing installation found":"Ready to install";
  view.detail="HelixSR 1.8, Model E, V762. Installed files do not confirm working gameplay or frame generation.";
  if(game.gameplay_warning)view.detail+=" "+game.gameplay_warning;
  view.nextStep=game.route==="direct"?"Choose AMD FSR in the game, then check gameplay.":"Review the OptiScaler proxy setup, then check gameplay.";
  view.color=game.enabled?"#22c55e":"#60a5fa";
  if(running){
    view.title="Game is running";view.detail="File and Steam launch changes are unavailable while the game is running.";
    view.nextStep="Close the game, then refresh status.";view.color="#f59e0b";
    view.primary.enabled=false;if(view.toggle)view.toggle.enabled=false;return view;
  }
  if(!source){
    view.title="Loading source status";view.detail="Wait for source status before reviewing a change.";
    view.nextStep="Refresh when source checking finishes.";view.color="#9ca3af";
    view.primary.enabled=false;if(view.toggle)view.toggle.enabled=false;
    view.canRemove=false;view.canRecover=false;return view;
  }
  if(game.recovery_available){
    view.title="Recovery available";view.detail=status?.summary||"An interrupted installation needs recovery.";
    view.nextStep="Recover the installation, then refresh status.";view.color="#f59e0b";
    view.primary={action:"recover",label:labels.recover,enabled:true};if(view.toggle)view.toggle.enabled=false;return view;
  }
  if(blocking || game.compatibility==="blocked" || !candidate || status?.can_modify!==true){
    view.title=blocking?.title||"Installation needs review";
    view.detail=blocking?.reason||status?.summary||game.reasons.join(" ")||"This game is not a supported DX12 installation candidate.";
    view.nextStep=blocking?.steps.join(" ")||"Review the installation status before making changes.";view.color="#f59e0b";
    if(!candidate && (game.managed||game.legacy)) view.primary={action:"remove",label:labels.remove,enabled:view.canRemove};
    else if(action!=="disable")view.primary.enabled=false;
    if(view.toggle && !game.enabled)view.toggle.enabled=false;
    return view;
  }
  if(action==="disable")return view;
  if(!source?.ready){
    view.title=source?"Source unavailable":"Loading source status";
    view.detail=source?.reason||"A verified local source is required to install or enable HelixSR.";
    view.nextStep="Refresh source status after the local source is ready.";view.color="#9ca3af";
  }else if(!executableReady){
    view.title="Choose the DX12 executable";view.detail="Select a scanned DX12 executable for OptiScaler.";
    view.nextStep="Choose an executable, then review the installation.";view.color="#f59e0b";
  }else if(view.needsDx12&&!selection.dx12){
    view.title="Confirm the DX12 renderer";view.detail="This game requires confirmation that DX12 is selected.";
    view.nextStep="Select DX12 in the game and confirm it here.";view.color="#f59e0b";
  }
  return view;
}
