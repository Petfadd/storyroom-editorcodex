/* Per-slot camera motion in the monitor: the same arithmetic as cinematic.py.
   A test (tests/test_cinematic.py) runs both and requires them to agree, so what the
   monitor shows is what the render draws. */
(function(root){
 const EASINGS=['linear','ease-in','ease-out','ease-in-out'];
 function ease(p,e){p=Math.min(1,Math.max(0,p));
  if(e==='ease-in')return p*p;if(e==='ease-out')return 1-(1-p)*(1-p);
  if(e==='ease-in-out')return .5-.5*Math.cos(Math.PI*p);return p}
 function camWindow(c,p){p=Math.min(1,p/(c.motion_end||1));const e=ease(p,c.easing);
  let z;
  if(c.preset==='portrait_reveal'){
   const turn=.58,zmid=c.zoom_mid??102;
   z=(p<=turn?c.zoom_start+(zmid-c.zoom_start)*ease(p/turn,'ease-in-out'):
    zmid+(c.zoom_end-zmid)*ease((p-turn)/(1-turn),'ease-in-out'))/100;
  }else z=(c.zoom_start+(c.zoom_end-c.zoom_start)*e)/100;
  const half=.5/z,cx=c.x_start+(c.x_end-c.x_start)*e,cy=c.y_start+(c.y_end-c.y_start)*e;
  return [z,Math.min(1-half,Math.max(half,cx)),Math.min(1-half,Math.max(half,cy))]}
 function isActive(c){return !!c&&(c.preset==='portrait_reveal'||c.zoom_start!==c.zoom_end||c.x_start!==c.x_end||c.y_start!==c.y_end||c.zoom_start!==100)}
 // Progress of a slot at time t (seconds, film clock): 0 on its first frame, 1 on its last.
 function slotProgress(inMs,outMs,t,fps){const frame=1000/(fps||30),span=outMs-inMs-frame;
  return span<=0?0:Math.min(1,Math.max(0,(t*1000-inMs)/span))}
 // CSS transform that shows the camera window of a full-frame layer.
 function camTransform(c,p){const [z,cx,cy]=camWindow(c,p);
  return `translate(${(-(cx-.5)*z*100).toFixed(4)}%,${(-(cy-.5)*z*100).toFixed(4)}%) scale(${z.toFixed(5)})`}
 const INTENSITY={subtle:[5,.03],medium:[10,.05],strong:[18,.08]};
 function camPreset(direction,intensity,focus,baseZoom){const [dz,dp]=INTENSITY[intensity]||INTENSITY.medium;
  const fx=focus?.[0]??.5,fy=focus?.[1]??.5,base=Math.max(100,Math.min(200,Math.round(baseZoom||100)));
  const c={zoom_start:base,zoom_end:base,x_start:fx,y_start:fy,x_end:fx,y_end:fy,easing:'ease-in-out'};
  if(direction==='portrait_reveal'){
   c.zoom_start=Math.min(200,Math.max(base+2*dz,120));
   c.zoom_mid=Math.max(base,102);
   c.zoom_end=Math.min(200,Math.max(base+dz+3,113));
   c.x_start=fx-dp*.35;c.x_end=fx+dp*.55;
   c.y_start=fy+dp*.15;c.y_end=fy-dp*.25;
  }
  else if(direction==='zoom_in')c.zoom_end=Math.min(200,base+dz);
  else if(direction==='zoom_out')c.zoom_start=Math.min(200,base+dz);
  else if(['pan_left','pan_right','pan_up','pan_down'].includes(direction)){
   const z=Math.max(base,Math.min(200,Math.ceil(dp<.45?100/(1-2*dp):200)));c.zoom_start=c.zoom_end=z;
   const s={pan_left:[1,0],pan_right:[-1,0],pan_up:[0,1],pan_down:[0,-1]}[direction];
   c.x_start=fx+s[0]*dp;c.x_end=fx-s[0]*dp;c.y_start=fy+s[1]*dp;c.y_end=fy-s[1]*dp;c.easing='linear'}
  else if(['push_left','push_right','push_up','push_down','reveal_left','reveal_right','drift_up_right','drift_down_left'].includes(direction)){
   const diagonal=['drift_up_right','drift_down_left'].includes(direction),amount=dp*(diagonal?.55:.75),dz2=Math.max(3,Math.min(dz,12));
   if(direction.startsWith('reveal')){c.zoom_start=Math.min(200,base+dz2);c.zoom_end=base}
   else{c.zoom_start=Math.max(base,Math.ceil(100/(1-2*amount)));c.zoom_end=Math.min(200,c.zoom_start+dz2)}
   const [sx,sy]={push_left:[-1,0],push_right:[1,0],push_up:[0,-1],push_down:[0,1],
    reveal_left:[-1,0],reveal_right:[1,0],drift_up_right:[.75,-.75],drift_down_left:[-.75,.75]}[direction];
   c.x_start=fx-sx*amount;c.x_end=fx+sx*amount;c.y_start=fy-sy*amount;c.y_end=fy+sy*amount;c.easing='ease-in-out';
  }
  c.preset=direction;
  for(const k of ['x_start','x_end','y_start','y_end'])c[k]=Math.round(Math.min(1,Math.max(0,c[k]))*1e4)/1e4;
  return c}
 const api={EASINGS,ease,camWindow,isActive,slotProgress,camTransform,camPreset};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.Cinematic=api;
})(typeof window!=='undefined'?window:globalThis);
