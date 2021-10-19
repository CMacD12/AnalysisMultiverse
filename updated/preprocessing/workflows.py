#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct  4 12:50:07 2021

@author: grahamseasons
"""
def smooth(warped, mask):#, susan, fwhm):
    #WORKFLOW ADAPTED FROM: https://nipype.readthedocs.io/en/latest/users/examples/fmri_fsl.html
    from nipype import Workflow, Node, IdentityInterface
    from nipype.interfaces.fsl import (BET, ImageMaths, ImageStats, SUSAN, IsotropicSmooth)
    import os, glob, re
    from functions import get_bright_thresh, getthreshop
    
    smooth = Workflow('smooth')
    smooth.base_dir = os.getcwd()
    
    susan = vars().get('susan', True)
    fwhm = vars().get('fwhm', 4)
    
    inputnode = Node(IdentityInterface(fields=['in_file']), name='inputnode')
    inputnode.inputs.in_file = warped
    
    outnode = Node(IdentityInterface(fields=['smoothed']), name='outnode')
    
    if susan:
        meanfunc = Node(ImageMaths(op_string='-Tmean', suffix='_mean'), name='meanfunc')
        meanfuncmask = Node(BET(mask=True, no_output=True, frac=0.3), name='meanfuncmask')
        maskfunc = Node(ImageMaths(suffix='_bet', op_string='-mas'), name='maskfunc')
        getthresh = Node(ImageStats(op_string='-p 2 -p 98'), name='getthreshold')
        threshold = Node(ImageMaths(out_data_type='char', suffix='_thresh'), name='threshold')
        
        medianval = Node(ImageStats(op_string='-k %s -p 50'), name='medianval')
        
        smooth_su = Node(SUSAN(fwhm=fwhm), name='smooth_su')
        
        smooth.connect([(inputnode, meanfunc, [('in_file', 'in_file')]),
                        (meanfunc, meanfuncmask, [('out_file', 'in_file')]),
                        (inputnode, maskfunc, [('in_file', 'in_file')]),
                        (meanfuncmask, maskfunc, [('mask_file', 'in_file2')]),
                        (maskfunc, getthresh, [('out_file', 'in_file')]),
                        (maskfunc, threshold, [('out_file', 'in_file')]),
                        (getthresh, threshold, [(('out_stat', getthreshop), 'op_string')]),
                        (inputnode, medianval, [('in_file', 'in_file')]),
                        (threshold, medianval, [('out_file', 'mask_file')]),
                        (medianval, smooth_su, [(('out_stat', get_bright_thresh), 'brightness_threshold')]),
                        (inputnode, smooth_su, [('in_file', 'in_file')]),
                        (smooth_su, outnode, [('smoothed_file', 'smoothed')]),
                        ])
                
        smooth.run()
        smoothed = glob.glob(os.getcwd() + '/smooth/smooth_su/*.nii*')[0]
    else:
        smooth_iso = Node(IsotropicSmooth(fwhm=fwhm, output_type='NIFTI'), name='smooth_iso')
        smooth.connect(inputnode, 'in_file', smooth_iso, 'in_file')
        smooth.connect(smooth_iso, 'out_file', outnode, 'smoothed')
        
        smooth.run()
        smoothed = glob.glob(os.getcwd() + '/smooth/smooth_iso/*.nii*')[0]
        
    return smoothed, glob.glob(os.getcwd() + '/smooth/**', recursive=True)
                        
def registration(T1w, mask, start_img, corrected_img, bet, wm_file):#, bbr, wm_thresh, warplater):
    from nipype.interfaces.fsl import FLIRT
    from nipype import IdentityInterface
    from nipype import Workflow, Node
    from os.path import join as opj
    import os, glob, re
    
    reg = Workflow(name='reg')
    reg.base_dir = os.getcwd()
    
    bbr = vars().get('bbr', True)
    #wmthresh = vars().get('wmthresh', True)
    #warplater = vars().get('warplater', True)
    
    regpre = Node(FLIRT(in_file=start_img, reference=bet, output_type='NIFTI_GZ'), name='regpre')
    
    applywarp = Node(FLIRT(in_file=corrected_img, reference=bet, output_type='NIFTI_GZ'), name='applywarp')
    
    outnode =  Node(IdentityInterface(fields=['warped','out_mat', 'mask']), name='outnode')
    
    if bbr:
        regbbr = Node(FLIRT(cost='bbr', reference=T1w, in_file=start_img, output_type='NIFTI_GZ',
                        schedule=opj(os.getenv('FSLDIR'), 'etc/flirtsch/bbr.sch')), name='regbbr')
        regbbr.inputs.wm_seg = wm_file
        #threshold = Node(Threshold(thresh=wmthresh, in_file=wm_file, args='-bin', output_type='NIFTI_GZ'), name="threshold")
        reg.connect([#(threshold, regbbr, [('out_file', 'wm_seg')]),
                     (regpre, regbbr, [('out_matrix_file', 'in_matrix_file')]),
                     (regbbr, applywarp, [('out_matrix_file', 'in_matrix_file')]),
                     (regbbr, outnode, [('out_matrix_file', 'out_mat')]),
                     ])
        node_reg = 'regbbr'
    else:
        reg.connect([(regpre, applywarp, [('out_matrix_file', 'in_matrix_file')]),
                     (regpre, outnode, [('out_matrix_file', 'out_mat')]),
                     ])
        node_reg = 'regpre'

    node_warp = 'applywarp'
        
    reg.run()
        
    out_mat = glob.glob(os.getcwd() + '/reg/' + node_reg + '/*.mat')[0]
    warped = glob.glob(os.getcwd() + '/reg/' + node_warp + '/*.nii*')[0]
        
    return out_mat, warped, glob.glob(os.getcwd() + '/reg/**', recursive=True)

def regress(unsmoothed, mc_par, segmentations, mask):
    from nipype import Node
    from nipype.interfaces.fsl import ImageMeants, Threshold, FLIRT, GLM
    from nipype.interfaces.fsl.maths import MeanImage
    from nipype.interfaces.base import CommandLine
    import numpy as np
    import nibabel as nib
    #from scipy import stats
    import os
    
    CSF = vars().get('CSF', True)
    WM = vars().get('WM', True)
    GLOBAL = vars().get('GLOBAL', True)
    params = np.loadtxt(mc_par)
    
    if vars().get('realignregress', True):
        params = np.zeros((params[0], 1))
        
    resample = False
    suffix = ''
    
    reference = Node(MeanImage(in_file=unsmoothed, dimension='T'), name='reference').run().outputs.out_file
    if nib.load(unsmoothed).shape[0:-1] != nib.load(mask).shape:
        resample = True
    
    if CSF:
        csfmask = segmentations[0]
        if resample:
            csfmask = Node(FLIRT(in_file=csfmask, reference=reference, apply_xfm=True, uses_qform=True), name='csfmask').run().outputs.out_file
        meancsf = Node(ImageMeants(in_file=unsmoothed, mask=csfmask), name='meancsf')
        csf = np.loadtxt(meancsf.run().outputs.out_file).reshape(-1, 1)
        params = np.hstack((params, csf))
        suffix += 'CSF_'
    if WM:
        wmmask = segmentations[2]
        if resample:
            wmmask = Node(FLIRT(in_file=wmmask, reference=reference, apply_xfm=True, uses_qform=True), name='wmmask').run().outputs.out_file
        meanwm = Node(ImageMeants(in_file=unsmoothed, mask=wmmask), name='meancsf')
        wm = np.loadtxt(meanwm.run().outputs.out_file).reshape(-1, 1)
        params = np.hstack((params, wm))
        suffix += 'WM_'
    if GLOBAL:
        meanglob = Node(ImageMeants(in_file=unsmoothed, mask=mask), name='meanglob')
        glob = np.loadtxt(meanglob.run().outputs.out_file).reshape(-1, 1)
        params = np.hstack((params, glob))
        suffix += 'GLOBAL'
        
    name_ = os.getcwd() + '/' + suffix
    #params = stats.zscore(params)
    np.savetxt(name_ + '.txt', params)
    cmd = ('Text2Vest {name_}.txt {name_}.mat').format(name_=name_)
    cl = CommandLine(cmd)
    cl.run().runtime
    
    if np.any(params):
        glm = Node(GLM(design=name_ + '.mat', in_file=unsmoothed), name='glm')
    
        regressed = glm.run()
        unsmoothed = regressed.outputs.out_res
    
    return unsmoothed

def toMNI(warplater, mniMask, brainmask, warp, warped, segmentations):
    from nipype.interfaces.fsl import ApplyWarp
    from nipype import MapNode
    if not warplater:
        warped = ApplyWarp(in_file=warped, ref_file=mniMask, field_file=warp)
        
        warped = warped.run().outputs.out_file
        brainmask = ApplyWarp(in_file=brainmask, ref_file=mniMask, field_file=warp, interp='nn').run().outputs.out_file
        segmentations = MapNode(ApplyWarp(in_file=segmentations, ref_file=mniMask, field_file=warp, interp='nn'), iterfield='in_file', name='warp_seg').run().outputs.out_file
    
    return warped, brainmask, segmentations

    
    
    
    
    
    
    
    
    
    
    