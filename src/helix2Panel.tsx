import {ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ConfirmModal, showModal} from "@decky/ui";
import {callable, openFilePicker, FileSelectionType} from "@decky/api";
import {useEffect, useRef, useState} from "react";
import {createArmadaReadRpc} from "./armadaReadRpc";
import {availableActions, changedOptions, helix2Labels, type Helix2Options, type Helix2State} from "./helix2View";

const rpc=<T,>(method:string,...args:unknown[]):Promise<T>=>callable<unknown[],T>(method)(...args);
const read=createArmadaReadRpc(rpc,15000);
type Library={games:{id:string;name:string}[];source:{ready:boolean;reason?:string;source?:string};warnings:string[]};
type Preview={token:string;summary:string;changes:string[]};
const fields:{key:keyof Helix2Options;label:string;values:string[];description:string}[]=[
  {key:"Int8",label:"INT8 network",values:["auto","on","off"],description:"On improved the tested 2.0 build. Compare quality and frame times on your driver."},
  {key:"WaveSize",label:"Wave size",values:["auto","64","32"],description:"WinNative can select 32 lanes. 64 is a diagnostic option; it is not a verified trail fix."},
  {key:"NetworkResolution",label:"Ultra Performance network",values:["fast","full"],description:"Fast uses a smaller network output in Ultra Performance. Full favors detail."},
  {key:"UseReactiveMask",label:"Reactive mask",values:["true","false"],description:"Keep the current choice unless comparing a specific visual problem."},
];

export function Helix2Panel() {
  const [library,setLibrary]=useState<Library>();
  const [gid,setGid]=useState("");
  const [state,setState]=useState<Helix2State>();
  const [options,setOptions]=useState<Helix2Options>({});
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const mounted=useRef(true),pending=useRef(false),generation=useRef(0);
  const dialog=useRef<{Close():void}|undefined>(undefined);
  function fail(cause:unknown) {if(mounted.current)setError((cause instanceof Error?cause.message:String(cause)).split("\n")[0].slice(0,500));}
  function finish() {pending.current=false;if(mounted.current)setBusy(false);}
  function begin() {if(pending.current||!mounted.current)return false;pending.current=true;setBusy(true);setError("");return true;}
  async function load(id?:string) {
    const version=++generation.current;
    const data=await read<Library>("helix2_library");
    const selected=data.games.find(g=>g.id===(id||gid))?.id||data.games[0]?.id||"";
    const fresh=selected?await read<Helix2State>("helix2_status",selected):undefined;
    if(!mounted.current||version!==generation.current)return;
    setLibrary(data);setGid(selected);setState(fresh);setOptions(fresh?.options||{});
  }
  async function refresh() {if(!begin())return;try{await load();}catch(cause){setState(undefined);fail(cause);}finally{finish();}}
  // Decky closes/unmounts the QAM view when a confirmation modal opens.
  // The modal must remain available for the user's explicit confirmation.
  useEffect(()=>{mounted.current=true;void refresh();return()=>{mounted.current=false;generation.current++;};},[]);
  async function chooseSource() {
    if(!begin())return;
    try {
      const folder=await openFilePicker(FileSelectionType.FOLDER,library?.source.source||"/var/home/armada",true,true);
      if(folder?.realpath&&mounted.current){await rpc("helix2_register_source",folder.realpath);await load();}
    }catch(cause){fail(cause);}finally{finish();}
  }
  async function act(action:string) {
    if(!availableActions(state).includes(action)||!begin())return;
    let shown=false;
    try {
      if(action==="recover") {
        shown=true;
        dialog.current=showModal(<ConfirmModal strTitle="Recover interrupted change" strDescription="Verify the transaction and restore its recorded files, or finish an already committed change. Conflicting files are preserved and reported for review." onCancel={finish} onOK={()=>{
          void (async()=>{try{await rpc("helix2_recover",gid);await load();}catch(cause){setState(undefined);fail(cause);}finally{finish();}})();
        }}/>);
        return;
      }
      const changes=action==="settings"?changedOptions(state!.options,options):undefined;
      const preview=await rpc<Preview>("helix2_preview",gid,action,changes);
      if(!mounted.current)return;
      shown=true;
      dialog.current=showModal(<ConfirmModal strTitle={helix2Labels[action]} strDescription={preview.summary+". "+preview.changes.join("; ")} onCancel={finish} onOK={()=>{
        void (async()=>{try{await rpc("helix2_execute",preview.token);await load();}catch(cause){setState(undefined);fail(cause);}finally{finish();}})();
      }}/>);
    }catch(cause){fail(cause);}finally{if(!shown)finish();}
  }
  const actions=availableActions(state);
  const dirty=state&&Object.keys(changedOptions(state.options,options)).length>0;
  return <PanelSection title="Adreno · HelixSR 2.0">
    <PanelSectionRow><div>PRAGMATA on Odin 3 / Armada Linux. Uses your locally built official 2.0 FSR drop-in.</div></PanelSectionRow>
    {error&&<PanelSectionRow><div style={{color:"#fbbf24"}}>{error}</div></PanelSectionRow>}
    <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void refresh()}>{busy?"Working…":"Refresh status"}</ButtonItem></PanelSectionRow>
    {library&&!library.games.length&&<PanelSectionRow><div>PRAGMATA was not found in Steam. This preview does not qualify other games or Android.</div></PanelSectionRow>}
    {library&&library.games.length>1&&<PanelSectionRow><DropdownItem label="Game" selectedOption={gid} rgOptions={library.games.map(g=>({label:g.name,data:g.id}))} disabled={busy} onChange={value=>{if(begin())void load(value.data).catch(fail).finally(finish);}}/></PanelSectionRow>}
    {state&&<PanelSectionRow><div><b>{state.state==="helix2"?"HelixSR 2.0 detected":state.state==="stock"?"Original FSR selected":"Installation needs review"}</b><p>{state.running?"Close the game before making changes.":state.reason||"Settings take effect on the next game launch."}</p></div></PanelSectionRow>}
    {actions.filter(a=>a!=="settings"&&a!=="remove").map(action=><PanelSectionRow key={action}><ButtonItem disabled={busy} onClick={()=>void act(action)}>{helix2Labels[action]}</ButtonItem></PanelSectionRow>)}
    {state?.managed&&state.state==="helix2"&&fields.map(field=><PanelSectionRow key={field.key}><DropdownItem label={field.label} description={field.description} selectedOption={options[field.key]??undefined} rgOptions={field.values.map(value=>({label:value,data:value}))} disabled={busy||!actions.includes("settings")} onChange={value=>setOptions(current=>({...current,[field.key]:value.data}))}/></PanelSectionRow>)}
    {actions.includes("settings")&&<PanelSectionRow><ButtonItem disabled={busy||!dirty} onClick={()=>void act("settings")}>Review settings change</ButtonItem></PanelSectionRow>}
    <PanelSectionRow><div>{library?.source.ready?"Local 2.0 source verified.":"To install or re-enable, choose the fsr3-drop-in folder built by the official 2.0 setup on this device."}</div></PanelSectionRow>
    <PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void chooseSource()}>Choose local 2.0 source</ButtonItem></PanelSectionRow>
    {actions.includes("remove")&&<PanelSectionRow><ButtonItem disabled={busy} onClick={()=>void act("remove")}>{helix2Labels.remove}</ButtonItem></PanelSectionRow>}
    <PanelSectionRow><div>Game quality, resolution, frame cap, driver, clocks and LSFG stay under their existing controls. Model data stays on this device. 3.x changes the FSR drop-in to HLX FSR 4 and is not interchangeable with this route.</div></PanelSectionRow>
  </PanelSection>;
}
