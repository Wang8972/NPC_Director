#!/usr/bin/env python3
"""Text-mode Unity protocol mock. Rehearsal by default; no model required."""
from __future__ import annotations
import argparse
import json
import time
import urllib.error
import urllib.request


class Client:
    def __init__(self,url):self.url=url.rstrip('/');self.sid='';self.view=None
    def call(self,path,body=None):
        data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
        request=urllib.request.Request(self.url+path,data=data,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=20) as r: result=json.load(r)
        except urllib.error.HTTPError as error:
            result=json.loads(error.read())
        if result.get('view'):self.view=result['view'];self.sid=self.view['session_id']
        if not result.get('ok'):print('未执行：',result.get('error','请求失败'))
        return result
    def command(self,name,**body):
        body.setdefault('expected_revision',self.view['revision'])
        return self.call('/sessions/'+self.sid+'/'+name,body)
    def job(self,job,interactive=True):
        if not job:return
        seen=set();base=f'/sessions/{self.sid}/talk/{job["id"]}'
        while True:
            for line in job.get('lines',[]):
                if line['id'] in seen:continue
                print('\n'+line['speaker']+'：'+line['text']);seen.add(line['id'])
                if interactive:input('回车表示已读完（之后才发送送达回执）…')
                self.call(base+'/ack',{'line_id':line['id']})
            if job['status'] in ('completed','failed','cancelled'):
                if job.get('error'):print(job['error'])
                if job.get('suggested_steps'):
                    print('AI建议（尚未执行）：',json.dumps(job['suggested_steps'],ensure_ascii=False))
                break
            time.sleep(.2)
            result=self.call(base);job=result.get('job') or job


def show(client):
    v=client.view;room=next(r for r in v['rooms'] if r['id']==v['room_id'])
    print('\n'+'='*50+'\n余灯 · 本地协议Mock（不是Unity Player）')
    print(room['title'],'|',v['chapter'],'| 救援刻',v['tick'],'|',v['mode'])
    print(v['objective'])
    print('人物：',', '.join(a['id']+' '+a['name'] for a in v['actors'] if a['id']!='player'))
    print('对象：',', '.join(o['id']+' '+o['label'] for o in v['objects']))
    print('物品：',', '.join(i['label']+'（'+(i['holder_id'] or i['connected_to'] or i['room_id'])+'）' for i in v['inventory']))
    if v['ending']:print('\n'+v['ending_title']+'\n'+v['ending_text'])


def smoke(client):
    assert client.call('/health')['app_id']=='last-light'
    assert client.call('/sessions',{'mode':'rehearsal'})['ok']
    assert not any(a['id']=='xiaoman' for a in client.view['actors'])
    p=client.command('plan',title='HTTP Mock检查',steps=[{'id':'s1','action_id':'clear_aisle','actor_id':'player','target_id':'aisle07','helpers':[],'depends_on':[]}]);assert p['ok']
    p=client.command('begin',plan_id=client.view['plans'][-1]['id']);assert p['ok']
    eid=client.view['execution']['id'];rev=client.view['revision']
    assert client.command('complete',execution_id=eid)['ok']
    assert client.view['tick']==1
    assert client.call(f'/sessions/{client.sid}/complete',{'execution_id':eid,'expected_revision':rev})['ok']
    assert client.view['tick']==1
    assert client.call(f'/sessions/{client.sid}/save',{})['ok']
    assert client.command('move',room_id='cabin06')['ok']
    assert client.call(f'/sessions/{client.sid}/restore',{})['ok']
    assert client.view['room_id']=='cabin07'
    print(json.dumps({'ok':True,'mode':'HTTP mock / no model','checks':['identity','privacy','plan','execution','duplicate','save','restore'],'session_id':client.sid},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8766')
    parser.add_argument('--mode',choices=['rehearsal','live'],default='rehearsal')
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args();client=Client(args.url)
    try:
        if args.smoke:smoke(client);return
        if client.call('/health').get('app_id')!='last-light':raise RuntimeError('目标地址不是余灯服务')
        if not client.call('/sessions',{'mode':args.mode})['ok']:return
        print('命令：look / move 房间ID / inspect 对象ID / talk NPC / actions / plan 动作ID / go / notes / save / restore / quit')
        while True:
            show(client);parts=input('\n> ').strip().split(maxsplit=1)
            if not parts:continue
            command=parts[0];arg=parts[1] if len(parts)>1 else ''
            if command in ('quit','exit'):break
            if command=='look':continue
            if command=='move':client.command('move',room_id=arg)
            elif command=='inspect':client.command('inspect',target_id=arg)
            elif command=='actions':
                for a in client.view['actions']:print(a['id'],a['label'],str(a['duration'])+'刻',a['blocked_reason'])
            elif command=='talk':
                if args.mode=='rehearsal':
                    for t in client.view.get('topics',[]):
                        if t['npc_id']==arg:print(t['id'],t['label'])
                    topic=input('选择预设主题ID：').strip();text=''
                else:topic='';text=input('你想说：')
                result=client.command('talk',npc_id=arg,text=text,topic_id=topic,audience=[arg]);client.job(result.get('job'))
            elif command=='plan':
                action=next((a for a in client.view['actions'] if a['id']==arg),None)
                if action is None:print('先用actions查看当前可以讨论的动作');continue
                actor=input('执行者（默认'+action['default_actor']+'）：').strip() or action['default_actor']
                helpers=input('助手ID，空格分隔，没有留空：').split()
                client.command('plan',title=action['label'],steps=[{'id':'s1','action_id':arg,'actor_id':actor,'target_id':action['target_id'],'helpers':helpers,'depends_on':[]}])
            elif command=='go':
                plan=next((p for p in reversed(client.view['plans']) if p['status'] not in ('completed','failed','cancelled')),None)
                if not plan:print('没有待执行计划');continue
                result=client.command('begin',plan_id=plan['id'])
                if result['ok']:
                    execution=client.view['execution'];print('[Mock] 执行并回报：',execution['action_id'],'本批',execution['duration'],'刻')
                    result=client.command('complete',execution_id=execution['id']);client.job(result.get('job'))
            elif command=='notes':
                for n in client.view['journal']:print(n['title']+'｜'+n['source']+'\n'+n['text'])
            elif command in ('save','restore'):client.call(f'/sessions/{client.sid}/{command}',{})
            else:print('未知命令；actions查看可执行动作，talk选择人物，plan/go提交真实行动。')
    except (OSError,RuntimeError) as error:raise SystemExit(str(error)+'\n请先启动 tools/run_server.py --port 8766')


if __name__=='__main__':main()
