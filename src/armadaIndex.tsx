import {ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ToggleField, ConfirmModal, showModal, staticClasses} from "@decky/ui";
import {callable, definePlugin, openFilePicker, FileSelectionType, toaster} from "@decky/api";
import {useEffect, useRef, useState} from "react";
import {FaAdjust} from "react-icons/fa";
import {createArmadaClient, type PreparedChange} from "./armadaClient";
import {eligibleGames, managedGames, selectInitialGame, statusArguments, viewGame, type Action, type Game, type Source} from "./armadaView";

type Library = {games:Game[]; warnings:string[]};
const rpc = <T,>(method:string,...args:unknown[]):Promise<T> => callable<unknown[],T>(method)(...args);
let preferred = "";
const card = {padding:"12px",borderRadius:"8px",background:"rgba(255,255,255,0.06)",overflowWrap:"anywhere" as const};
function errorText(error:unknown):string {
  const message=error instanceof Error ? error.message : typeof error==="string" ? error : "The request could not be completed. Refresh status and try again.";
  return message.split("\n")[0].slice(0,500);
}

function Content() {
  const [data,setData]=useState<Library>();
  const [source,setSource]=useState<Source>();
  const [selected,setSelected]=useState("");
  const [game,setGame]=useState<Game>();
  const [executable,setExecutable]=useState<string>();
  const [dx12,setDx12]=useState(false);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [modal,setModal]=useState(false);
  const [error,setError]=useState("");
  const [advanced,setAdvanced]=useState(false);
  const [settings,setSettings]=useState(false);
  const [reviewId,setReviewId]=useState("");
  const mounted=useRef(true), active=useRef(""), generation=useRef(0), operation=useRef(false), polling=useRef(false);
  const latestData=useRef<Library|undefined>(undefined), latestGame=useRef<Game|undefined>(undefined), currentExe=useRef<string|undefined>(undefined);
  const client=useRef(createArmadaClient(rpc,SteamClient.Apps));
  const dialog=useRef<{Close():void}|undefined>(undefined);
  function choose(id:string,review=false) {
    if (operation.current) return;
    generation.current++; active.current=id; preferred=review ? preferred : id;
    latestGame.current=undefined; currentExe.current=undefined;
    setSelected(id); setReviewId(review ? id : ""); setGame(undefined); setExecutable(undefined); setDx12(false); setError(""); setLoading(!!id);
  }
  function isCurrent(id:string,version:number) {return mounted.current && active.current===id && generation.current===version;}
  async function readStatus(id=active.current,version=generation.current) {
    if (!id || polling.current) return;
    const scanned=latestData.current?.games.find(item=>item.id===id);
    const metadata=latestGame.current?.id===id ? latestGame.current : scanned;
    if (!metadata) return;
    polling.current=true;
    try {
      const fresh=await rpc<Game>("armada_status",...statusArguments(metadata,currentExe.current));
      if (!isCurrent(id,version) || fresh.id!==id) return;
      const merged={...scanned,...fresh}; latestGame.current=merged; setGame(merged); setLoading(false); setError("");
    } catch (cause) {if (isCurrent(id,version)) {setError(errorText(cause)); setLoading(true);}}
    finally {
      polling.current=false;
      if (mounted.current && (active.current!==id || generation.current!==version)) void readStatus();
    }
  }
  async function refreshLibrary() {
    const version=generation.current;
    const [fresh,files]=await Promise.all([rpc<Library>("library"),rpc<Source>("armada_source_status")]);
    if (!mounted.current || version!==generation.current) return;
    latestData.current=fresh; setData(fresh); setSource(files);
    const stillPresent=fresh.games.some(item=>item.id===active.current);
    const id=stillPresent ? active.current : selectInitialGame(fresh.games,preferred);
    if (id!==active.current) {
      generation.current++; active.current=id; preferred=id; latestGame.current=undefined; currentExe.current=undefined;
      setSelected(id); setReviewId(""); setExecutable(undefined); setDx12(false); setGame(undefined);
    }
    setLoading(!!id);
    if (id) await readStatus(id,generation.current);
    else setLoading(false);
  }
  function begin():boolean {
    if (operation.current || !mounted.current) return false;
    if (polling.current) {setError("Fresh game status is being checked. Wait for it to finish, then try again.");return false;}
    operation.current=true; setBusy(true); setError(""); return true;
  }
  function finish() {operation.current=false; if (mounted.current) {setBusy(false); setModal(false);}}
  async function refresh() {
    if (!begin()) return;
    try {await refreshLibrary();} catch(cause) {if(mounted.current)setError(errorText(cause));} finally {finish();}
  }
  useEffect(()=>{
    mounted.current=true;
    void refresh();
    return ()=>{mounted.current=false; generation.current++; dialog.current?.Close();};
  },[]);
  useEffect(()=>{
    if (!selected) return;
    let live=true;
    const update=()=>{if(live && !operation.current && !polling.current) void readStatus();};
    update();
    const timer=setInterval(update,15000);
    return ()=>{live=false;clearInterval(timer);};
  },[selected,executable]);
  async function chooseSource() {
    if (!begin()) return;
    const version=generation.current;
    try {
      const folder=await openFilePicker(FileSelectionType.FOLDER,source?.source || "/var/home/armada",true,true);
      if (folder?.realpath && mounted.current && version===generation.current) {
        const verified=await rpc<Source>("armada_register_source",folder.realpath);
        if (mounted.current && version===generation.current) setSource(verified);
      }
    } catch(cause) {if(mounted.current && version===generation.current)setError(errorText(cause));} finally {finish();}
  }
  async function apply(change:PreparedChange,id:string,version:number) {
    try {
      if (!isCurrent(id,version)) return;
      const result=await client.current.applyPreview(change);
      if (!isCurrent(id,version)) return;
      toaster.toast({title:"HelixSR Armada",body:result.message,duration:6500});
      // Refresh scanned management metadata before requesting executable-sensitive status.
      latestGame.current=undefined; currentExe.current=undefined; setExecutable(undefined); setDx12(false);
      await refreshLibrary();
    } catch(cause) {if(isCurrent(id,version))setError(errorText(cause));} finally {finish();}
  }
  async function act(action:Action) {
    if (!game || loading || !begin()) return;
    const chosen=game,id=chosen.id,version=generation.current;
    const gates=viewGame(chosen,source,{executable,dx12});
    const allowed=action==="remove" ? gates.canRemove : action==="recover" ? gates.canRecover : action==="enable" || action==="disable" ? gates.toggle?.enabled || gates.primary?.action===action && gates.primary.enabled : gates.primary?.action===action && gates.primary.enabled;
    if (!allowed) {setError(gates.nextStep);finish();return;}
    try {
      const change=await client.current.prepareAction(chosen,{executable,dx12},action);
      if (!isCurrent(id,version)) {finish();return;}
      if (action==="enable" || action==="disable") {await apply(change,id,version);return;}
      setModal(true);
      let accepted=false;
      dialog.current=showModal(<ConfirmModal bDisableBackgroundDismiss
        strTitle={action==="remove" ? "Remove HelixSR" : action==="recover" ? "Recover interrupted change" : action==="adopt" ? "Manage existing HelixSR" : action==="update" ? "Apply pinned V762 files" : "Install HelixSR"}
        strDescription={<div style={{overflowWrap:"anywhere"}}><p>{change.preview.name}</p><p>{change.preview.warning}</p><p>{change.preview.files.length} files covered by the installation record. Steam launch settings will be read back and verified when needed.</p><p>HelixSR 1.8 · Model E · V762. Check gameplay after installation.</p></div>}
        strOKButtonText="Apply" onCancel={()=>{if(!accepted)finish();}}
        onOK={()=>{if(accepted || !isCurrent(id,version))return;accepted=true;dialog.current?.Close();dialog.current=undefined;void apply(change,id,version);}}/>);
    } catch(cause) {if(isCurrent(id,version))setError(errorText(cause));finish();}
  }
  async function repair() {
    if (!game || loading || game.installation_status?.running || !begin()) return;
    const id=game.id,version=generation.current;
    try {
      const body=await client.current.repairLaunch(game);
      if (isCurrent(id,version)) {toaster.toast({title:"HelixSR Armada",body,duration:6500});await refreshLibrary();}
    } catch(cause) {if(isCurrent(id,version))setError(errorText(cause));} finally {finish();}
  }
  const candidates=eligibleGames(data?.games || []), records=managedGames(data?.games || []);
  const view=viewGame(game,source,{executable,dx12});
  const blocked=busy || modal || loading || !!game?.installation_status?.running;
  const options=candidates.map(item=>({label:item.name,data:item.id}));
  const statusCard=<><PanelSectionRow><div style={card}><div style={{fontWeight:600,color:view.color}}>{view.title}</div><p>{view.detail}</p><div>{view.nextStep}</div></div></PanelSectionRow>
    {game && view.needsExecutable && <PanelSectionRow><DropdownItem label="DX12 executable" disabled={blocked} selectedOption={executable} rgOptions={(game.executable_choices || []).map(item=>({label:item.path,data:item.path}))} onChange={value=>{
      if(operation.current)return; generation.current++;currentExe.current=value.data;setExecutable(value.data);setDx12(false);setLoading(true);setError("");
    }}/></PanelSectionRow>}
    {game && view.needsDx12 && <PanelSectionRow><ToggleField label="DX12 is selected in this game" description="Confirm the renderer in the game's own settings." checked={dx12} disabled={busy || modal || !!game.installation_status?.running} onChange={value=>{if(!operation.current)setDx12(value);}}/></PanelSectionRow>}
    {view.primary && (!view.toggle || !["enable","disable"].includes(view.primary.action)) && <PanelSectionRow><ButtonItem disabled={blocked || !view.primary.enabled} onClick={()=>void act(view.primary!.action)}>{view.primary.label}</ButtonItem></PanelSectionRow>}
    {view.toggle && <PanelSectionRow><ToggleField label="HelixSR enabled" description={view.toggle.checked ? "Use original to return to the stock upscaler." : "Enable the installed V762 upscaler."} checked={view.toggle.checked} disabled={blocked || !view.toggle.enabled} onChange={value=>void act(value ? "enable" : "disable")}/></PanelSectionRow>}
    {busy && <PanelSectionRow><div>{modal ? "Review the proposed change to continue." : "Checking and applying the change. Please wait."}</div></PanelSectionRow>}
    {loading && selected && !busy && <PanelSectionRow><div>Waiting for fresh game status. Actions are unavailable until it is verified.</div></PanelSectionRow>}
    {error && <PanelSectionRow><div style={{color:"#ffb3b3",overflowWrap:"anywhere"}}>{error}</div></PanelSectionRow>}</>;
  return <><PanelSection title="Games">
    <PanelSectionRow><div>HelixSR 1.8 · Model E · V762</div></PanelSectionRow>
    <PanelSectionRow><div>{data ? `${candidates.length} detected DX12 candidate${candidates.length===1 ? "" : "s"}` : "Checking installed games…"}</div></PanelSectionRow>
    {options.length>0 && <PanelSectionRow><DropdownItem label="Game" disabled={busy || modal} rgOptions={options} selectedOption={reviewId ? undefined : selected} onChange={value=>choose(value.data)}/></PanelSectionRow>}
    {!options.length && data && <PanelSectionRow><div>No detected DX12 candidates. Existing installation records are available in Advanced troubleshooting.</div></PanelSectionRow>}
    {!reviewId && statusCard}
    {source && !source.ready && <><PanelSectionRow><div>{source.reason || "Choose the verified local V762 source before installation."}</div></PanelSectionRow><PanelSectionRow><ButtonItem disabled={busy || modal} onClick={()=>void chooseSource()}>Choose local V762 files</ButtonItem></PanelSectionRow></>}
    <PanelSectionRow><ButtonItem disabled={busy || modal} onClick={()=>void refresh()}>Refresh games and status</ButtonItem></PanelSectionRow>
  </PanelSection><PanelSection title="Settings">
    <PanelSectionRow><ToggleField label="Show settings" checked={settings} onChange={setSettings}/></PanelSectionRow>
    {settings && <><PanelSectionRow><div>{source?.ready ? "Local V762 source verified." : source?.reason || "Source has not been verified."}</div></PanelSectionRow><PanelSectionRow><ButtonItem disabled={busy || modal} onClick={()=>void chooseSource()}>Choose local V762 files</ButtonItem></PanelSectionRow><PanelSectionRow><div>Helix runtime: {game?.helix_runtime || "No runtime information reported."}</div></PanelSectionRow><PanelSectionRow><div>Frame generation: {game?.framegen_summary || "No frame generation status reported."} Lossless Scaling VK2 is controlled separately.</div></PanelSectionRow></>}
  </PanelSection><PanelSection title="Advanced troubleshooting">
    <PanelSectionRow><ToggleField label="Show advanced" checked={advanced} disabled={busy || modal} onChange={value=>{setAdvanced(value);if(!value && reviewId)choose(selectInitialGame(data?.games || [],preferred));}}/></PanelSectionRow>
    {advanced && <>
      {records.length>0 && <PanelSectionRow><DropdownItem label="Existing installation records" description="Includes records needing review or restoration." disabled={busy || modal} selectedOption={reviewId || undefined} rgOptions={records.map(item=>({label:item.name,data:item.id}))} onChange={value=>choose(value.data,true)}/></PanelSectionRow>}
      {reviewId && statusCard}
      {game && <><PanelSectionRow><div style={card}><div>Route: {view.routeLabel}</div><div>Installed: {game.installed_version || "Not recorded"} · {game.installed_model || "Model not recorded"}</div><div>Helix runtime: {game.helix_runtime || "Not reported"}</div><div>Frame generation: {game.framegen_summary || "Not reported"}. Lossless Scaling VK2 is controlled separately.</div><div>Folder: {game.folder}</div>{game.reasons.map((reason,index)=><p key={index}>{reason}</p>)}{game.installation_status?.issues?.map(issue=><div key={issue.code}><p>{issue.title}: {issue.reason}</p>{issue.steps.map((step,index)=><p key={index}>{step}</p>)}</div>)}</div></PanelSectionRow>
        {view.canRecover && view.primary?.action!=="recover" && <PanelSectionRow><ButtonItem disabled={blocked} onClick={()=>void act("recover")}>Recover interrupted change</ButtonItem></PanelSectionRow>}
        {view.canRemove && <PanelSectionRow><ButtonItem disabled={blocked} onClick={()=>void act("remove")}>Remove HelixSR and restore original</ButtonItem></PanelSectionRow>}
        <PanelSectionRow><ButtonItem disabled={blocked} onClick={()=>void repair()}>Repair owned launch settings</ButtonItem></PanelSectionRow>
        {game.logs?.map(log=><PanelSectionRow key={log.path}><div style={card}><div>{log.path}</div>{log.excerpt && <pre style={{whiteSpace:"pre-wrap",fontSize:"12px"}}>{log.excerpt}</pre>}</div></PanelSectionRow>)}
      </>}
      {data?.warnings.map((warning,index)=><PanelSectionRow key={index}><div>{warning}</div></PanelSectionRow>)}
      <PanelSectionRow><div>About: plugin 0.3.0. HelixSR by lonewolf0622. Unofficial Armada integration by Blackheart909. This adaptation uses pinned local V762 assets. Upstream downloads and model switching are unavailable. Installation and saved settings do not prove gameplay compatibility.</div></PanelSectionRow>
      {source?.source && <PanelSectionRow><div style={{overflowWrap:"anywhere"}}>Local source: {source.source}</div></PanelSectionRow>}
    </>}
  </PanelSection></>;
}
export default definePlugin(()=>({name:"HelixSR Decky Armada",titleView:<div className={staticClasses.Title}>HelixSR Armada</div>,content:<Content/>,icon:<FaAdjust/>}));
