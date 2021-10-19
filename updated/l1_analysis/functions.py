#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Oct 15 10:02:31 2021

@author: grahamseasons
"""
from updated.functions import insert
from nipype.utils.functions import getsource
from updated.workflows import write_out
import re

def data_driven(mask, unsmoothed, k, kcc, TR, lp=0.01, hp=0.1):
    from nipype import Node
    from nipype.interfaces.afni.utils import ReHo
    from nipype.interfaces.fsl.maths import TemporalFilter, Threshold#, UnaryMaths
    
    bpfilter = Node(TemporalFilter(in_file=unsmoothed), name='bpfilter')
    #HZ to sigma conversion taken from: https://www.jiscmail.ac.uk/cgi-bin/webadmin?A2=fsl;fc5b33c5.1205
    bpfilter.inputs.lowpass_sigma = 1 / (2 * TR * lp)
    bpfilter.inputs.highpass_sigma = 1 / (2 * TR * hp)
    
    filtered = bpfilter.run().outputs.out_file
    
    reho = Node(ReHo(in_file=filtered), name='reho')
    reho.inputs.neighborhood = k
    reho.inputs.mask_file = mask#Node(UnaryMaths(in_file=mask, operation='bin'), name='binmask').run().outputs.out_file
    rehomap = reho.run().outputs.out_file
    
    thresh = Node(Threshold(in_file=rehomap, args='-bin'))
    thresh.inputs.thresh = kcc
    
    return thresh.run().outputs.out_file

def warp(in_file, ref, warp):
    from nipype import Node
    from nipype.interfaces.fsl import ApplyWarp
    mni = Node(ApplyWarp(ref_file=ref, field_file=warp), name='mni')
    mni.inputs.in_file = in_file
    return mni.run().outputs.out_file

def invert(warp, brain):
    from nipype import Node
    from nipype import InvWarp
    invwarp = Node(InvWarp(warp=warp, ref=brain), name='invwarp')
    return invwarp.run().outputs.inverse_warp

def function_str(name, dic=''):   
    from updated.l1_analysis.workflows import sessioninfo
    valid_functions = ['sessioninfo']
    if name in valid_functions:
        func_str = getsource(vars()[name])
        try: 
            out = []
            for names in dic[name].keys():
                out.append(re.search('[A-Za-z]+_([A-Za-z_]+)', names).group(1))
                
            ind = func_str.find('):')
            params = ', ' + ', '.join(out)
            func_str = insert(func_str, ind, params)
            out = [element for element in out if '_' in element]
            
            workflowfind = list(re.finditer('\n(\n)(\s+)[A-Za-z]+.run()', func_str))
            if not workflowfind:
                workflowfind = list(re.finditer('\n(\n)(\s+)[A-Za-z\s=]+.run()', func_str))
            
            for search in reversed(workflowfind):
                ind = search.start(1)
                block = '\n' + search.group(2) + (search.group(2) + search.group(2)).join(["for param in {params}:\n",
                "search = re.search('([A-Za-z]+)_([A-Za-z_]+)', param)\n",
                "setattr(vars()[search.group(1)].inputs, search.group(2), vars()[param])\n"])
                
                func_str = insert(func_str, ind, block).format(params=out)
            return func_str, re.search('def ' + name + '\(([A-Za-z_,0-9\s]+)\)', func_str).group(1).split(', ')
        except:
            return func_str, re.search('def ' + name + '\(([A-Za-z_,0-9\s]+)\)', func_str).group(1).split(', ')

def correct_task_timing(session_info, TR, discard):
    for i, info in enumerate(session_info):
        for j, task in enumerate(info['cond']):
            try:
                for k, num in enumerate(task['onset']):
                    session_info[i]['cond'][j]['onset'][k] = num - (TR * discard)
            except:
                return session_info
                        
    return session_info

def get_sink(inputs, files):
    if type(files) != list:
        files = [files]
        
    func_str = getsource(write_out)
    ind = func_str.find('):')
    params = ', ' + ', '.join(inputs)
    func_str = insert(func_str, ind, params)
    
    search = re.search('\n(\n)(\s+)(setattr)', func_str)
    ind = search.start(1)
    
    block = '\n' + search.group(2) + (search.group(2) + search.group(2)).join(["if os.path.isdir(out):\n",
        "for file in {files}:\n",
        "    file = out + '/' + file\n",
        "    if os.path.isdir(file) or os.path.isfile(file):\n",
        "        setattr(sink.inputs, 'pipelines/' + task + '.@' + str(i) + file, vars()[file])\n"])
        
    func_str = insert(func_str, search.start(3), "\n    "+search.group(2))
    func_str = insert(func_str, search.start(3), "else:")
    func_str = insert(func_str, ind, block)
        
    return func_str.format(files=str(files))


def contrasts(session_info):
    contrasts = []
    identities = []
    for info in session_info:
        condition_names = []
        for task in info['cond']:
            condition_names.append(task['name'])
                    
        num_tasks = len(condition_names)
        ind_con = []
        ind_ident = []
        group_con = []
        group_ident = []
        if num_tasks > 1:
            for i, condition in enumerate(condition_names):
                weights_specific = [0] * num_tasks
                weights_specific[i] = 1
                ind_con.append([condition, 'T', condition_names, weights_specific])
                ind_ident.append(condition)
                new_cond = condition + ' > others'
                weights_specific = [-1/(num_tasks - 1)] * num_tasks
                weights_specific[i] = 1
                group_con.append([new_cond, 'T', condition_names, weights_specific])
                group_ident.append(new_cond)
                
            contrasts.append(['average', 'T', condition_names, [1/num_tasks]*num_tasks])
            identities.append('average')
                   
            contrasts += ind_con
            identities += ind_ident
            contrasts += group_con
            identities += group_ident
                   
            #contrasts.append(['activation', 'F', ind_con])
            #identities.append('activation')
            #contrasts.append(['differences', 'F', group_con])
            #identities.append('differences')
        else:
            contrasts.append([condition_names[0], 'T', condition_names, [1]])
            identities.append(condition_names[0])
                
    return identities, contrasts