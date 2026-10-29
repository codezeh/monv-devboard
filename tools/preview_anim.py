#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预览「部位局部动画」效果：模拟固件按部位加位移"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw
import numpy as np
import part_regions as PR

BG=(58,70,104)
PART={0:'body',1:'head',2:'armL',3:'armR'}

def tri(p,per,amp):
    if per<2: return 0
    p%=per; h=per//2
    if h==0: return 0
    return p*amp//h if p<h else (per-p)*amp//h

def anim(state,ph):
    ox=oy=0; tint=0
    px_=[0]*4; py_=[0]*4
    if state=='IDLE':
        oy=tri(ph,2400,1); py_[1]=-tri(ph,2400,1)
    elif state=='WALK':
        oy=tri(ph,600,1); sw=tri(ph,600,4)
        py_[2]=sw; py_[3]=-sw; px_[1]=1 if ((ph//150)&1) else -1
    elif state=='HURT':
        tint=2; ox=3 if ((ph//50)&1) else -3; py_[1]=-3
    elif state=='JUMP':
        if ph<400:
            oy=-tri(ph,400,6); sw=tri(ph,400,4); py_[2]=-sw; py_[3]=-sw
    elif state=='ATTACK':
        if ph<350:
            sw=tri(ph,350,5); py_[2]=-sw; py_[3]=-sw; oy=-tri(ph,350,1)
    elif state=='SLEEP':
        tint=1; oy=tri(ph,4000,1); py_[1]=2
    return ox,oy,px_,py_,tint

def frame(img, rects, state, ph):
    fw,fh=img.size
    out=Image.new('RGB',(fw,fh),BG)
    src=img.load(); dst=out.load()
    ox,oy,px_,py_,tint=anim(state,ph)
    # 逐像素判断部位（用矩形，与固件同优先级）
    for y in range(fh):
        for x in range(fw):
            r,g,b,a=src[x,y]
            if a<128: continue
            p=0
            def inr(i): return rects[i][0]<=x<=rects[i][2] and rects[i][1]<=y<=rects[i][3]
            if inr(2): p=2
            elif inr(3): p=3
            elif inr(1): p=1
            X=x+ox+px_[p]; Y=y+oy+py_[p]
            if 0<=X<fw and 0<=Y<fh:
                if tint==1: dst[X,Y]=(r>>1,g>>1,b>>1)
                elif tint==2: dst[X,Y]=((r*2+765)//5,(g*2)//5,(b*2)//5)
                else: dst[X,Y]=(r,g,b)
    return out

def main():
    sp=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','skin_user.png')
    fw,fh,px,rects,texel = PR.export_frame(sp)
    img=Image.new('RGBA',(fw,fh))
    p=img.load()
    for y in range(fh):
        for x in range(fw):
            c=px[y*fw+x]
            if c==0xF81F: p[x,y]=(0,0,0,0)
            else: p[x,y]=(((c>>11)&0x1F)*255//31,((c>>5)&0x3F)*255//63,(c&0x1F)*255//31,255)
    shots=[('IDLE',600),('WALK',150),('HURT',50),('JUMP',200),('ATTACK',175),('SLEEP',1000)]
    frames=[frame(img,rects,s,ph) for s,ph in shots]
    PAD,LAB=8,14; cols=3
    cw,ch=fw+PAD, fh+PAD+LAB
    sheet=Image.new('RGB',(cols*cw+PAD,2*ch+PAD),(18,18,22))
    d=ImageDraw.Draw(sheet)
    for i,(f,(n,ph)) in enumerate(zip(frames,shots)):
        cx=PAD+(i%cols)*cw; cy=PAD+(i//cols)*ch
        d.text((cx,cy),f'{n} ({ph}ms)',fill=(220,220,220))
        sheet.paste(f,(cx,cy+LAB))
    sheet=sheet.resize((sheet.width*2,sheet.height*2),Image.NEAREST)
    sheet.save(os.path.join(os.path.dirname(os.path.abspath(__file__)),'preview_anim.png'))
    print('saved preview_anim.png',sheet.size)

if __name__=='__main__': main()
