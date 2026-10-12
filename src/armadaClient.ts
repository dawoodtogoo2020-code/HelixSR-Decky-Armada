import {armadaOptions, restoreArmadaOptions, type LaunchAddon} from "./armadaLaunch";
import {proxyOptions} from "./launchOptions";
import {statusArguments, type Action, type Game, type Selection} from "./armadaView";

export type Preview = {token:string; action:string; name:string; warning:string; files:string[]; launch_environment?:Record<string,string>; launch_addon?:LaunchAddon|null};
export type PreparedChange = {game:Game; selection:Selection; action:Action; preview:Preview};
export type Receipt = {before:string; after:string; pending?:{before:string; after:string; restore:boolean; nonce:string}};
type Steam = {
  RegisterForAppDetails(appid:number, callback:(detail:{strLaunchOptions?:unknown})=>void):{unregister():void};
  SetAppLaunchOptions(appid:number, value:string):void;
};

export function createArmadaClient(rpc:<T>(method:string,...args:unknown[])=>Promise<T>, steam:Steam, timeoutMs=5000) {
  let inFlight=false;
  function appId(game:Game):number {
    if (!game.appid || !/^\d+$/.test(game.appid)) throw new Error("A valid Steam game ID is required for launch settings.");
    const id=Number(game.appid);
    if (!Number.isSafeInteger(id) || id<=0 || id>4294967295) throw new Error("A valid Steam game ID is required for launch settings.");
    return id;
  }
  function locked<T>(work:()=>Promise<T>):Promise<T> {
    if (inFlight) return Promise.reject(new Error("Another change is in progress. Wait for it to finish."));
    inFlight=true;
    return work().finally(()=>{inFlight=false;});
  }
  async function freshGame(game:Game):Promise<Game> {
    appId(game);
    // A review may remain open while the user launches the game. Recheck before
    // Steam writes as well as file execution; a cached UI status is insufficient.
    // No executable is needed for the running/record check, avoiding stale picks.
    const fresh=await rpc<Game>("armada_status",game.id);
    if (fresh.id!==game.id) throw new Error("Game status changed unexpectedly. Refresh and review the action again.");
    const current={...game,...fresh};
    appId(current);
    if (current.installation_status?.running) throw new Error("Close the game before making changes, then refresh status.");
    return current;
  }
  function readLaunchOptions(appid:number):Promise<string> {
    if (!Number.isSafeInteger(appid) || appid<=0 || appid>4294967295) return Promise.reject(new Error("A valid Steam game ID is required."));
    return new Promise((resolve,reject)=>{
      let subscription:{unregister():void}|undefined, settled=false, unregistered=false;
      const cleanup=()=>{
        clearTimeout(timer);
        if (subscription && !unregistered) {unregistered=true; subscription.unregister();}
      };
      const timer=setTimeout(()=>{
        if (settled) return;
        settled=true; cleanup(); reject(new Error("Steam did not return launch settings. Try again after Steam is ready."));
      },timeoutMs);
      try {
        subscription=steam.RegisterForAppDetails(appid, detail=>{
          if (settled || typeof detail.strLaunchOptions!=="string") return;
          settled=true; cleanup(); resolve(detail.strLaunchOptions);
        });
        if (settled) cleanup();
      } catch (error) {settled=true; cleanup(); reject(error);}
    });
  }
  async function save(game:Game,before:string,after:string,restore:boolean,nonce?:string):Promise<string> {
    if (before===after && !nonce) return before;
    const intent=nonce ? {nonce} : await rpc<{nonce:string}>("prepare_launch_options",game.id,before,after,restore);
    if (before!==after) steam.SetAppLaunchOptions(appId(game),after);
    const actual=await readLaunchOptions(appId(game));
    if (actual!==after) throw new Error("Steam did not save the exact launch settings. The pending receipt was preserved. Repair launch settings before retrying.");
    await rpc("finalize_launch_options",game.id,intent.nonce,actual);
    return actual;
  }
  async function changeLaunch(game:Game,preview:Preview,restore:boolean):Promise<{actual:string;notice?:string}> {
    const before=await readLaunchOptions(appId(game));
    const receipt=await rpc<Receipt|null>("owned_launch_options",game.id,before);
    if (receipt?.pending) {
      const pending=receipt.pending;
      if (pending.restore!==restore) throw new Error("An interrupted launch change needs repair before this action.");
      if (before!==pending.before && before!==pending.after) throw new Error("Steam launch settings changed outside the plugin. Review them before repair.");
      return {actual:await save(game,before,pending.after,restore,pending.nonce)};
    }
    if (restore && !receipt) return {actual:before,notice:"Steam options were preserved because there is no owned launch receipt. Review existing options manually."};
    if (!restore && !preview.launch_environment) throw new Error("The preview has no verified launch environment. Refresh and review the action again.");
    const after=restore ? restoreArmadaOptions(before,receipt) : armadaOptions(before,preview.launch_environment!,game.route==="optiscaler",proxyOptions,preview.launch_addon);
    return {actual:await save(game,before,after,restore)};
  }
  function prepareAction(game:Game,selection:Selection,action:Action):Promise<PreparedChange> {
    return locked(async()=>{
      appId(game);
      if (game.installation_status?.running) throw new Error("Close the game before making changes.");
      const args=statusArguments(game,selection.executable);
      if (["install","update","adopt"].includes(action)) await rpc("armada_prepare",...args);
      const preview=await rpc<Preview>("armada_preview",args[0],action,selection.dx12,...args.slice(1));
      return {game:{...game},selection:{...selection},action,preview};
    });
  }
  function applyPreview(change:PreparedChange):Promise<{message:string}> {
    return locked(async()=>{
      const {preview,action}=change;
      const game=await freshGame(change.game);
      if (action==="disable") await rpc("remember_launch_addon",game.id,await readLaunchOptions(appId(game)));
      const enabling=["install","update","enable","adopt"].includes(action);
      const launch=enabling ? await changeLaunch(game,preview,false) : undefined;
      const result=launch ? await rpc<{message:string}>("armada_execute",preview.token,launch.actual) : await rpc<{message:string}>("armada_execute",preview.token);
      if (action==="disable" || action==="remove") {
        const restored=await changeLaunch(game,preview,true);
        if (restored.notice) return {message:result.message+" "+restored.notice};
      }
      return result;
    });
  }
  function repairLaunch(game:Game):Promise<string> {
    return locked(async()=>{
      const current=await freshGame(game);
      const before=await readLaunchOptions(appId(current));
      const receipt=await rpc<Receipt|null>("owned_launch_options",current.id,before);
      if (!receipt) return "No owned launch receipt exists. Current Steam options were preserved.";
      if (receipt.pending) {
        const pending=receipt.pending;
        if (pending.restore && current.managed && current.enabled) throw new Error("Use original first, then restore owned launch settings.");
        if (before!==pending.before && before!==pending.after) throw new Error("Steam options do not match the pending receipt. Current settings were preserved; review them manually.");
        // Resume only the exact receipted intent. save() performs another fresh,
        // exact readback before finalization, including when Steam already saved it.
        await save(current,before,pending.after,pending.restore,pending.nonce);
        return "The pending launch change is verified. Review the game action again.";
      }
      if (current.managed && current.enabled) throw new Error("Use original first, then restore owned launch settings.");
      await save(current,before,restoreArmadaOptions(before,receipt),true);
      return "Original launch settings restored and verified.";
    });
  }
  return {readLaunchOptions,prepareAction,applyPreview,repairLaunch};
}
