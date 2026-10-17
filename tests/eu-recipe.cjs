const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const ROOT=path.join(__dirname,'..');
const read=p=>fs.readFileSync(path.join(ROOT,p),'utf8');
const map=JSON.parse(read('tools/eu_file_id_map.json'));
const EU_ONLY=[17,18,33,172,173,174,176,177,178,179,208,209,210,265,266,269,270];
// Minimal YAML reader for the generated recipe: name -> fields.
function yamlEntries(dir){
 const out={};
 for(const file of fs.readdirSync(path.join(ROOT,dir)).filter(f=>f.startsWith('reloc_')&&f.endsWith('.yml'))){
  for(const block of read(path.join(dir,file)).split('\n\n')){
   const name=block.match(/^([A-Za-z_][A-Za-z0-9_]*):$/m);
   const id=block.match(/file_id:\s*(\d+)/);
   if(!name||!id)continue;
   out[name[1]]={file_id:Number(id[1]),file:file,offset:block.match(/offset:\s*0x([0-9A-F]+)/)[1],
                 size:block.match(/size:\s*0x([0-9A-F]+)/)[1],
                 decompressed:block.match(/decompressed_size:\s*0x([0-9A-F]+)/)[1],
                 symbol:block.match(/symbol:\s*(\S+)/)[1]};
  }
 }
 return out;
}

test('EU id map covers every US file, strictly monotone, ending on the last EU file',()=>{
 const ids=map.eu_id_by_us_id;
 assert.equal(ids.length,2132);
 assert.equal(map.eu_file_count,2149);
 assert.ok(ids.every(id=>id>=0&&id<2149),'every US file id resolves to a real EU file');
 for(let i=1;i<ids.length;i++)assert.ok(ids[i]>ids[i-1],`non-monotone at ${i}`);
 assert.equal(ids[ids.length-1],2148,'the last US file maps to the last EU file');
});

test('the EU id step function rises by exactly the EU-only file count',()=>{
 const ids=map.eu_id_by_us_id;
 const missing=[];for(let eu=0;eu<2149;eu++)if(!ids.includes(eu))missing.push(eu);
 assert.deepEqual(missing,EU_ONLY,'only the localised EU-only files are unclaimed');
 const steps=[];
 for(let i=1;i<ids.length;i++){const jump=ids[i]-ids[i-1];if(jump!==1)steps.push(jump);}
 assert.ok(steps.length>0&&steps.every(step=>step>=2),'ids only ever jump forward over inserted files');
 assert.equal(missing.length,steps.reduce((sum,step)=>sum+step-1,0));
});

test('yamls/eu mirrors yamls/us names with the mapped EU ids',()=>{
 const us=yamlEntries('BattleShip/yamls/us');
 const eu=yamlEntries('BattleShip/yamls/eu');
 assert.equal(Object.keys(us).length,2132);
 assert.deepEqual(Object.keys(eu).sort(),Object.keys(us).sort());
 for(const [name,entry] of Object.entries(us)){
  const mapped=eu[name];
  assert.equal(mapped.file_id,map.eu_id_by_us_id[entry.file_id],`${name} id`);
  assert.equal(mapped.symbol,entry.symbol);
  assert.equal(mapped.file,entry.file,'entries stay in the same category file');
  assert.ok(mapped.offset!==entry.offset||mapped.file_id!==entry.file_id,'EU offsets are re-derived');
 }
});

test('generated torch id map inverts the recipe mapping',()=>{
 const header=read('BattleShip/torch/src/factories/ssb64/RelocEuFileMap.h');
 assert.match(header,/kEuRelocFileCount = 2149/);
 const body=header.slice(header.indexOf('kUsIdByEuId[kEuRelocFileCount] = {'),header.indexOf('};'));
 const values=(body.match(/0x[0-9A-F]{4}/g)||[]).map(v=>parseInt(v,16));
 assert.equal(values.length,2149);
 assert.equal(values.filter(v=>v===0xFFFF).length,EU_ONLY.length);
 EU_ONLY.forEach(eu=>assert.equal(values[eu],0xFFFF,`EU-only file ${eu} has no US id`));
 map.eu_id_by_us_id.forEach((eu,us)=>assert.equal(values[eu],us,`EU ${eu} -> US ${us}`));
});

test('both engines agree on the reloc table layout for each region',()=>{
 const factory=read('BattleShip/torch/src/factories/ssb64/RelocFactory.h');
 const derive=read('BattleShip/port/css_icons/stage_assets_derive.cpp');
 for(const [file,text] of [['RelocFactory.h',factory],['stage_assets_derive.cpp',derive]]){
  assert.match(text,/0x001AC870u|0x1AC870/,`${file} knows the US table`);
  assert.match(text,/0x00262E20u|0x262E20/,`${file} knows the EU table`);
  assert.match(text,/2149/,`${file} knows the EU file count`);
  assert.match(text,/2132/,`${file} knows the US file count`);
 }
});

test('port-added stage art uses the mapped EU file ids',()=>{
 const derive=read('BattleShip/port/css_icons/stage_assets_derive.cpp');
 const stages=[['final_destination',96],['metal_cavern',98],['battlefield',97]];
 for(const [name,us] of stages){
  const row=derive.match(new RegExp(`\\{ "${name}",\\s*(0x[0-9A-Fa-f]+|\\d+),\\s*(0x[0-9A-Fa-f]+|\\d+),`));
  assert.ok(row,`${name} row missing`);
  const parse=v=>v.startsWith('0x')?parseInt(v,16):Number(v);
  assert.equal(parse(row[1]),us,'US id');
  assert.equal(parse(row[2]),map.eu_id_by_us_id[us],`${name} EU id`);
 }
});

test('config.yml selects the EU recipe for the European ROM hash',()=>{
 const config=read('BattleShip/config.yml');
 assert.match(config,/e2929e10fccc0aa84e5776227e798abc07cedabf:[\s\S]*?path: yamls\/us/);
 assert.match(config,/6ee8a41fef66280ce3e3f0984d00b96079442fb9:[\s\S]*?path: yamls\/eu/);
});

test('external reloc references are rewritten out of the EU id space',()=>{
 const factory=read('BattleShip/torch/src/factories/ssb64/RelocFactory.cpp');
 assert.match(factory,/#include "RelocEuFileMap\.h"/);
 assert.match(factory,/if \(L\.europe\)/);
 assert.match(factory,/kUsIdByEuId\[euId\]/);
});

test('the launcher accepts both regions and namespaces their saves',()=>{
 const launcher=read('web/launcher.js');
 assert.match(launcher,/e2929e10fccc0aa84e5776227e798abc07cedabf/);
 assert.match(launcher,/6ee8a41fef66280ce3e3f0984d00b96079442fb9/);
 // The launcher builds the engine query with URLSearchParams, which serialises
 // `savekey:region.saveKey` into the ?savekey= the shell reads back.
 assert.match(launcher,/savekey:region\.saveKey/);
 assert.match(launcher,/smash64\.native\.sram\.us/);
 assert.match(launcher,/smash64\.native\.sram\.eu/);
 const save=read('BattleShip/port/port_save.cpp');
 assert.match(save,/globalThis\.__smash64SramKey/);
 assert.match(save,/smash64\.native\.sram\.us/);
});

test('the packaged recipe ships every supported region',()=>{
 const script=read('BattleShip/scripts/package_web.sh');
 assert.match(script,/TORCH_REGIONS="\$\{TORCH_REGIONS:-us eu\}"/);
 const dist='BattleShip/web-dist';
 if(fs.existsSync(dist)){
  for(const region of ['us','eu'])assert.ok(fs.existsSync(path.join(dist,'torch','yamls',region)),`web-dist ships yamls/${region}`);
 }
});
