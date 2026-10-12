type Token={start:number;end:number;value:string};
export type LaunchAddon={helper:string;sha256:string;environment:{ENABLE_GAMESCOPE_WSI:string}};
const keys=["PROTON_USE_ARM64","VKD3D_SHADER_OVERRIDE"];
const armadaWrapper="/usr/libexec/armada/armada-game-launch";
const helperPin="f08628ec276495e8402f69651a1314bc1ab50b57dc36c280d5f2f3fa32d0c205";
function words(input:string):Token[] {
  if(input.length>16384||/[\x00-\x1f\x7f$`\\]/.test(input))throw new Error("These launch options need manual review.");
  const result:Token[]=[];let i=0;
  while(i<input.length){
    if(input[i]===" "){i++;continue;} const start=i;let quote="",value="";
    while(i<input.length){const c=input[i];
      if(quote){if(c===quote)quote="";else value+=c;}
      else if(c==="'"||c==='"')quote=c;
      else if(c===" ")break;
      else{if(/[;&|<>()*?\[\]{}#!~]/.test(c))throw new Error("Shell commands need manual review.");value+=c;}i++;
    }
    if(quote)throw new Error("Launch option quotes are incomplete.");result.push({start,end:i,value});
  }
  const commands=result.filter(t=>t.value.includes("%command%"));
  if(commands.length>1||commands.some(t=>input.slice(t.start,t.end)!=="%command%"))throw new Error("The Steam command needs manual review.");
  return result;
}
function withAddon(base:string,addon?:LaunchAddon|null):string {
  if(!addon)return base;
  if(typeof addon.helper!=="string"||!addon.helper.startsWith("/")||/[\x00-\x1f\x7f'"$`\\]/.test(addon.helper)||
    !addon.helper.endsWith("/PRAGMATA Mod Files/Combined-Helix-LSFG-20261012/pragmata-combined-launch.py")||
    addon.sha256!==helperPin||Object.keys(addon.environment).join(",")!=="ENABLE_GAMESCOPE_WSI"||addon.environment.ENABLE_GAMESCOPE_WSI!=="0")
    throw new Error("The saved combined launcher needs review. Current options were preserved.");
  const tokens=words(base);let leading=0;
  while(leading<tokens.length&&/^[A-Za-z_][A-Za-z0-9_]*=/.test(base.slice(tokens[leading].start,tokens[leading].end)))leading++;
  const wrappers=tokens.filter(t=>t.value===armadaWrapper);
  if(wrappers.length!==1)throw new Error("The combined launcher requires one Armada launch wrapper. Current options were preserved.");
  const wsi=tokens.filter(t=>t.value.startsWith("ENABLE_GAMESCOPE_WSI="));
  if(wsi.length>1||wsi.some(t=>tokens.indexOf(t)>=leading||t.value!=="ENABLE_GAMESCOPE_WSI=0"))
    throw new Error("An existing Gamescope WSI setting needs review. Current options were preserved.");
  const wrapper=wrappers[0],at=tokens.indexOf(wrapper);
  const helpers=tokens.filter(t=>t.value.endsWith("/pragmata-combined-launch.py"));
  if(helpers.length){
    if(helpers.length!==1||helpers[0].value!==addon.helper||tokens[at-1]!==helpers[0]||tokens[at-2]?.value!=="/usr/bin/python3")
      throw new Error("An existing combined launcher needs review. Current options were preserved.");
  }else{
    if(tokens[at-2]?.value==="/usr/bin/python3")throw new Error("An existing Python launcher needs review. Current options were preserved.");
    base=base.slice(0,wrapper.start)+`/usr/bin/python3 '${addon.helper}' `+base.slice(wrapper.start);
  }
  return wsi.length?base:"ENABLE_GAMESCOPE_WSI=0 "+base;
}
export function armadaOptions(before:string,env:Record<string,string>,proxy:boolean,mergeProxy?:(value:string)=>string,addon?:LaunchAddon|null):string {
  if(Object.keys(env).sort().join(",")!==keys.slice().sort().join(",")||env.PROTON_USE_ARM64!=="1"||!/^Z:\/[^\x00-\x1f'"$`\\]*\/shader-override$/.test(env.VKD3D_SHADER_OVERRIDE))throw new Error("The V762 launch environment is invalid.");
  if(proxy&&!mergeProxy)throw new Error("OptiScaler launch settings are unavailable.");
  let base=withAddon(proxy?mergeProxy!(before):before,addon);const tokens=words(base);let leading=0;
  while(leading<tokens.length&&/^[A-Za-z_][A-Za-z0-9_]*=/.test(base.slice(tokens[leading].start,tokens[leading].end)))leading++;
  const wrapper=tokens.find(t=>t.value==="/usr/libexec/armada/armada-game-launch"),command=tokens.findIndex(t=>t.value==="%command%");
  const inner=!!wrapper&&command>=3&&tokens[command-3].value==="/usr/bin/env"&&keys.every((key,i)=>tokens[command-2+i].value===key+"="+env[key]);
  for(const key of keys){const matches=tokens.filter(t=>t.value.startsWith(key+"="));
    const outer=matches.filter(t=>!inner||tokens.indexOf(t)<command-2||tokens.indexOf(t)>=command);
    if(outer.length>1||outer.some(t=>tokens.indexOf(t)>=leading||t.value!==key+"="+env[key]))throw new Error(`An existing ${key} setting needs review. Current options were preserved.`);
  }
  const additions=keys.filter(key=>!tokens.slice(0,leading).some(t=>t.value.startsWith(key+"="))).map(key=>`${key}='${env[key]}'`);
  if(wrapper&&!inner){
    if(command<0)throw new Error("The Armada wrapper needs a Steam command.");
    const at=tokens[command].start;
    base=base.slice(0,at)+"/usr/bin/env "+keys.map(key=>`${key}='${env[key]}'`).join(" ")+" "+base.slice(at);
  }
  if(!tokens.some(t=>t.value==="%command%")){
    if(tokens.slice(leading).some(t=>!t.value.startsWith("-")))throw new Error("Launch options without a Steam command need manual review.");
    const end=leading?tokens[leading-1].end:0;
    base=end?base.slice(0,end)+" %command%"+base.slice(end):"%command%"+(base?" "+base:"");
  }
  return additions.length?additions.join(" ")+" "+base:base;
}
export function restoreArmadaOptions(actual:string,receipt:{before:string;after:string}|null):string {
  if(!receipt)throw new Error("There is no saved launch setting to restore.");
  if(actual!==receipt.after)throw new Error("Launch settings changed outside this plugin. Review them before restoring.");return receipt.before;
}
