import {ButtonItem,DropdownItem,PanelSection,PanelSectionRow,ToggleField,ConfirmModal,showModal,staticClasses} from "@decky/ui";
import {callable,definePlugin,openFilePicker,toaster,FileSelectionType} from "@decky/api";
import {proxyOptions} from "./launchOptions";
import {useEffect,useState} from "react";
import {FaAdjust} from "react-icons/fa";
import {armadaOptions,restoreArmadaOptions,type LaunchAddon} from "./armadaLaunch";
type Game={id:string;name:string;appid?:string;folder:string;route:string|null;compatibility:string;reasons:string[];managed:boolean;enabled:boolean;legacy:boolean;dx12_confirmation_needed:boolean;executable_choices?:{path:string;dx12:boolean}[];selected_executable?:string;installation_status?:{running:boolean};helix_runtime?:string};
type Source={ready:boolean;reason?:string;source?:string};
type Library={games:Game[];warnings:string[]};
type Preview={token:string;action:string;name:string;warning:string;files:string[];launch_environment?:Record<string,string>;launch_addon?:LaunchAddon|null};
type Receipt={before:string;after:string;pending?:{before:string;after:string;restore:boolean;nonce:string}};
const library=callable<[],Library>("library"),status=callable<[string,string?],Game>("armada_status");
const sourceStatus=callable<[],Source>("armada_source_status"),registerSource=callable<[string],Source>("armada_register_source");
const prepare=callable<[string,string?],unknown>("armada_prepare"),preview=callable<[string,string,boolean,string?],Preview>("armada_preview");
const execute=callable<[string,string?],{message:string}>("armada_execute"),ownedLaunch=callable<[string,string],Receipt|null>("owned_launch_options");
const prepareLaunch=callable<[string,string,string,boolean],{nonce:string}>("prepare_launch_options"),finalizeLaunch=callable<[string,string,string],unknown>("finalize_launch_options");
const rememberAddon=callable<[string,string],{remembered:boolean}>("remember_launch_addon");
async function launchOptions(appid:number):Promise<string>{return new Promise((resolve,reject)=>{
  let subscription:{unregister():void}|undefined;
  const timer=setTimeout(()=>{subscription?.unregister();reject(new Error("Steam did not return launch settings."));},5000);
  subscription=SteamClient.Apps.RegisterForAppDetails(appid,detail=>{clearTimeout(timer);subscription?.unregister();resolve(detail.strLaunchOptions);});
});}
async function changeLaunch(game:Game,p:Preview):Promise<string>{
  if(!game.appid)throw new Error("This preview requires a Steam game. Other launchers need manual launch settings.");
  const appid=Number(game.appid),before=await launchOptions(appid),receipt=await ownedLaunch(game.id,before);
  const restore=["disable","remove"].includes(p.action);
  if(receipt?.pending){
    if(receipt.pending.restore!==restore)throw new Error("Repair the interrupted launch-setting change first.");
    SteamClient.Apps.SetAppLaunchOptions(appid,receipt.pending.after);
    const actual=await launchOptions(appid);
    await finalizeLaunch(game.id,receipt.pending.nonce,actual);return actual;
  }
  if(restore&&!receipt){
    toaster.toast({title:"HelixSR Armada",body:"Game files were restored. Existing Steam launch options have no plugin receipt and were preserved; review them manually.",duration:7000});
    return before;
  }
  const after=restore?restoreArmadaOptions(before,receipt):armadaOptions(before,p.launch_environment!,game.route==="optiscaler",proxyOptions,p.launch_addon);
  if(after===before)return before;
  const intent=await prepareLaunch(game.id,before,after,restore);SteamClient.Apps.SetAppLaunchOptions(appid,after);
  const actual=await launchOptions(appid);if(actual!==after)throw new Error("Steam did not save the launch settings. Game files were preserved.");
  await finalizeLaunch(game.id,intent.nonce,actual);return actual;
}
async function repairLaunch(game:Game):Promise<string>{
  if(!game.appid)throw new Error("Steam launch settings are unavailable for this game.");
  const appid=Number(game.appid),before=await launchOptions(appid),receipt=await ownedLaunch(game.id,before);
  if(!receipt)return "No interrupted or owned launch-setting change remains.";
  if(receipt.pending){
    SteamClient.Apps.SetAppLaunchOptions(appid,receipt.pending.after);
    const actual=await launchOptions(appid);
    await finalizeLaunch(game.id,receipt.pending.nonce,actual);
    return "Interrupted launch-setting change completed. Review the game action again.";
  }
  if(game.managed&&game.enabled)return "V762 launch settings are verified. Use the stock upscaler before restoring them.";
  const after=restoreArmadaOptions(before,receipt),intent=await prepareLaunch(game.id,before,after,true);
  SteamClient.Apps.SetAppLaunchOptions(appid,after);
  await finalizeLaunch(game.id,intent.nonce,await launchOptions(appid));return "Original launch settings restored.";
}
let lastSelected="";
function Content(){
  const [data,setData]=useState<Library>(),[source,setSource]=useState<Source>(),[selected,setSelected]=useState(lastSelected),[game,setGame]=useState<Game>();
  const [executable,setExecutable]=useState<string>(),[dx12,setDx12]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notes,setNotes]=useState(false),[review,setReview]=useState(false);
  const [revision,setRevision]=useState(0);
  async function run<T>(fn:()=>Promise<T>):Promise<T|undefined>{setBusy(true);setError("");try{return await fn();}catch(e){setError(e instanceof Error?e.message:String(e));return undefined;}finally{setBusy(false);}}
  async function refresh(){const result=await run(async()=>({data:await library(),source:await sourceStatus()}));if(!result)return;setData(result.data);setSource(result.source);
    const id=selected||result.data.games.find(g=>g.appid==="3357650")?.id||result.data.games[0]?.id||"";setSelected(id);lastSelected=id;setRevision(v=>v+1);}
  useEffect(()=>{void refresh();},[]);
  useEffect(()=>{if(!selected)return;let live=true;setGame(undefined);setDx12(false);void status(selected,executable).then(g=>{if(live)setGame(g);}).catch(e=>{if(live)setError(String(e));});return()=>{live=false;};},[selected,executable,revision]);
  async function chooseSource(){await run(async()=>{const folder=await openFilePicker(FileSelectionType.FOLDER,source?.source||"/var/home/armada",true,true);if(folder?.realpath)setSource(await registerSource(folder.realpath));});}
  async function act(action:string){if(!game)return;const chosen=game;
    const p=await run(async()=>{if(["install","update","adopt"].includes(action))await prepare(chosen.id,executable);return await preview(chosen.id,action,dx12,executable);});if(!p)return;setReview(true);
    const dialog=showModal(<ConfirmModal bDisableBackgroundDismiss strTitle={`${action==="adopt"?"Manage existing":action.charAt(0).toUpperCase()+action.slice(1)} V762`}
      strDescription={<div style={{overflowWrap:"anywhere"}}><p>{p.name}: {p.warning}</p><p>HelixSR 1.8.0 with V762 Snapdragon fixes. Confirm gameplay on this device.</p>{action==="remove"&&<p>Removal restores the original Steam launch settings and clears the saved combined-launcher attachment. Independently installed LSFG files remain.</p>}{p.launch_addon&&<p>The verified PRAGMATA combined launcher will be attached to the current Steam settings.</p>}<p>{p.files.length} game files are covered by the installation record.</p></div>}
      strOKButtonText="Apply" onCancel={()=>setReview(false)} onOK={()=>{dialog.Close();setReview(false);void run(async()=>{
        const restoring=["disable","remove"].includes(action);
        if(action==="disable"){
          if(!chosen.appid)throw new Error("Steam launch settings are unavailable for this game.");
          await rememberAddon(chosen.id,await launchOptions(Number(chosen.appid)));
        }
        const actual=["install","update","enable","adopt"].includes(action)?await changeLaunch(chosen,p):undefined;
        const result=await execute(p.token,actual);
        if(restoring)await changeLaunch(chosen,p);
        toaster.toast({title:"HelixSR Armada",body:result.message,duration:5000});setGame(await status(chosen.id,executable));setData(await library());
      });}}/>);
  }
  const disabled=busy||review;
  return <><PanelSection title="Snapdragon V762">
    <PanelSectionRow><div>HelixSR 1.8.0 · Model E · Armada</div></PanelSectionRow>
    <PanelSectionRow><div>PRAGMATA gameplay is confirmed. Other games still need testing.</div></PanelSectionRow>
    <PanelSectionRow><div>{source?.ready?"Your local V762 files are verified.":source?.reason||"Checking local V762 files…"}</div></PanelSectionRow>
    <PanelSectionRow><ButtonItem disabled={disabled} onClick={()=>void chooseSource()}>Choose local V762 files</ButtonItem></PanelSectionRow>
  </PanelSection><PanelSection title="Game">
    <PanelSectionRow><DropdownItem label="Installed Steam game" disabled={disabled} rgOptions={(data?.games||[]).map(g=>({label:g.name,data:g.id}))} selectedOption={selected} onChange={v=>{setExecutable(undefined);setSelected(v.data);lastSelected=v.data;}}/></PanelSectionRow>
    {game?.executable_choices&&game.executable_choices.length>1&&<PanelSectionRow><DropdownItem label="Game executable" disabled={disabled} selectedOption={executable||game.selected_executable} rgOptions={game.executable_choices.map(x=>({label:x.path,data:x.path}))} onChange={v=>setExecutable(v.data)}/></PanelSectionRow>}
    {game&&<><PanelSectionRow><div>{game.managed?game.enabled?"V762 enabled":"Stock upscaler enabled":game.legacy?"Existing HelixSR installation":"V762 not installed"}</div></PanelSectionRow>
      {game.installation_status?.running&&<PanelSectionRow><div>Game running. Close it before installation or toggling.</div></PanelSectionRow>}
      {game.dx12_confirmation_needed&&<PanelSectionRow><ToggleField label="I have selected DX12 in this game" checked={dx12} onChange={setDx12} disabled={disabled}/></PanelSectionRow>}
      {game.reasons.length>0&&<PanelSectionRow><div>{game.reasons.join(" ")}</div></PanelSectionRow>}
      {game.managed?<><PanelSectionRow><ButtonItem disabled={disabled} onClick={()=>void act(game.enabled?"disable":"enable")}>{game.enabled?"Use stock upscaler":"Enable V762"}</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem disabled={disabled} onClick={()=>void act("remove")}>Remove V762 from this game</ButtonItem></PanelSectionRow></>:<PanelSectionRow><ButtonItem disabled={disabled||!source?.ready} onClick={()=>void act(game.legacy?"adopt":"install")}>{game.legacy?"Manage existing V762":"Install V762"}</ButtonItem></PanelSectionRow>}
      <PanelSectionRow><ButtonItem disabled={disabled} onClick={()=>void act("recover")}>Recover interrupted change</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem disabled={disabled} onClick={()=>void run(async()=>{const body=await repairLaunch(game);toaster.toast({title:"HelixSR Armada",body,duration:5000});setGame(await status(game.id,executable));})}>Repair launch settings</ButtonItem></PanelSectionRow>
    </>}
    <PanelSectionRow><ButtonItem disabled={disabled} onClick={()=>void refresh()}>Refresh status</ButtonItem></PanelSectionRow>
    {error&&<PanelSectionRow><div style={{color:"#ffb3b3",overflowWrap:"anywhere"}}>{error}</div></PanelSectionRow>}
  </PanelSection><PanelSection title="Details">
    <PanelSectionRow><ToggleField label="Show installation details" checked={notes} onChange={setNotes}/></PanelSectionRow>
    {notes&&<><PanelSectionRow><div>Local personal files are used. This plugin does not download or share NVIDIA weights or generated kernels. Ordinary upstream updates are blocked for V762.</div></PanelSectionRow>
      {game?.helix_runtime&&<PanelSectionRow><div>{game.helix_runtime}</div></PanelSectionRow>}
      {data?.warnings.map((w,i)=><PanelSectionRow key={i}><div>{w}</div></PanelSectionRow>)}</>}
    <PanelSectionRow><div>HelixSR by lonewolf0622. Unofficial Snapdragon adaptation and Decky integration by Blackheart909.</div></PanelSectionRow>
  </PanelSection></>;
}
export default definePlugin(()=>({name:"HelixSR Decky Armada",titleView:<div className={staticClasses.Title}>HelixSR Armada</div>,content:<Content/>,icon:<FaAdjust/>}));
