from __future__ import division
import pkg_resources
import motmot.cam_iface.choose as cam_iface_choose

cam_iface = cam_iface_choose.import_backend( 'mega', 'ctypes' )

import numpy as nx
import time, sys, os
from optparse import OptionParser

# for save mode:
import motmot.FlyMovieFormat.FlyMovieFormat as FlyMovieFormat
import Queue
import threading

def main():
    usage = '%prog [options]'

    parser = OptionParser(usage)

    parser.add_option("--device-num", type="int",default = None,
                      help="device number", dest='device_num')
                      
    parser.add_option("--mode-num", type="int",default = None,
                      help="mode number")

    parser.add_option("--frames", type="int",
                      help="number of frames (default = infinite)",
                      default = None)

    parser.add_option("--save", action='store_true',
                      help="save frames to .fmf")
                  
    parser.add_option("--trigger-mode", type="int",
                      help="set trigger mode",
                      default=None, dest='trigger_mode')

    parser.add_option("--roi", type="string",
                      help="set camera region of interest (left,bottom,width,height)",
                      default=None)
                      
    parser.add_option("--use-computer-timestamps", action='store_true',
                      help="use computer clock instead of camera clock for timestamps", dest='use_comp_time')

    parser.add_option("--run-time", type="float",
                      help="time (in seconds) to run (default = infinite)",
                      default = None, dest='run_time')
                      
    parser.add_option("--framerate", type="float",
                      help="framerate (in frames/sec)",
                      default = None)
                      
    parser.add_option("--prefix", type="string",
                      help="prefix for saved file",
                      default = None)
                      
    parser.add_option("--camera-properties", type="string",
                      help="set camera properties to auto or onepush (lock at auto-chosen values)",
                      default = None, dest='camera_properties')
                                            
    (options, args) = parser.parse_args()

    if options.roi is not None:
        try:
            options.roi = tuple(map(int,options.roi.split(',')))
        except:
            print >> sys.stderr, "--roi option could not be understood. Use 4 "\
                "comma-separated integers (L,B,W,H)"
        assert len(options.roi)==4,"ROI must have 4 components (L,B,W,H)"

    print 'options.mode_num',options.mode_num

    doit(device_num=options.device_num,
         mode_num=options.mode_num,
         save=options.save,
         max_frames = options.frames,
         trigger_mode=options.trigger_mode,
         roi=options.roi,
         use_comp_time=options.use_comp_time,
         run_time=options.run_time,
         framerate=options.framerate,
         prefix=options.prefix,
         camera_properties=options.camera_properties)

def save_func( fly_movie, save_queue ):
    while 1:
        fnt = save_queue.get()
        frame,timestamp = fnt
        fly_movie.add_frame(frame,timestamp)

def doit(device_num=None,
         mode_num=None,
         num_buffers=30,
         save=False,
         max_frames=None,
         trigger_mode=None,
         roi=None,
         use_comp_time=False,
         run_time=None,
         framerate=None,
         prefix=None,
         camera_properties=None
         ):
    if device_num is None:
        device_num = 0
    num_modes = cam_iface.get_num_modes(device_num)
    for this_mode_num in range(num_modes):
        mode_str = cam_iface.get_mode_string(device_num,this_mode_num)
        print 'mode %d: %s'%(this_mode_num,mode_str)
        if mode_num is None:
            if 'DC1394_VIDEO_MODE_FORMAT7_0' in mode_str and 'MONO8' in mode_str:
                mode_num=this_mode_num
    
    if mode_num is None:
        mode_num=0
    print 'choosing mode %d'%(mode_num,)

    cam = cam_iface.Camera(device_num,num_buffers,mode_num)
    
    if prefix is not None and save is not True:
        print 'saving file'
        save = True

    if save:
        format = cam.get_pixel_coding()
        depth = cam.get_pixel_depth()
        if prefix is not None:
            filename = time.strftime( prefix + '%Y%m%d_%H%M%S.fmf' )
        else:
            filename = time.strftime( 'simple%Y%m%d_%H%M%S.fmf' )
        fly_movie = FlyMovieFormat.FlyMovieSaver(filename,
                                                 version=3,
                                                 format=format,
                                                 bits_per_pixel=depth,
                                                 )
        save_queue = Queue.Queue()
        save_thread = threading.Thread( target=save_func, args=(fly_movie,save_queue))
        save_thread.setDaemon(True)
        save_thread.start()
    ALLOWED_FRAMERATE_DEV = .5
    MAX_FRAMERATE = 10000
    low_framerate_mode = False
    if framerate is not None:
        cam.set_framerate(framerate)
        actual_framerate = cam.get_framerate()
        if framerate/actual_framerate < ALLOWED_FRAMERATE_DEV:
            low_framerate_mode = True
            cam.set_framerate(MAX_FRAMERATE)
            actual_framerate = cam.get_framerate()
            last_time = time.time()
            ifi = framerate
                
    n_trigger_modes = cam.get_num_trigger_modes()
    print "Trigger modes:"
    for i in range(n_trigger_modes):
        print ' %d: %s'%(i,cam.get_trigger_mode_string(i))
    if trigger_mode is not None:
        cam.set_trigger_mode_number( trigger_mode )
    print 'Using trigger mode %d'%(cam.get_trigger_mode_number())
    
    #----------start camera----------------
    cam.start_camera()
    if roi is not None:
        cam.set_frame_roi( *roi )
        actual_roi = cam.get_frame_roi()
        if roi != actual_roi:
            raise ValueError("could not set ROI. Actual ROI is %s."%(actual_roi,))
    
    num_props = cam.get_num_camera_properties()
    if camera_properties is 'auto' or 'onepush':
        for p in range(num_props):
            if cam.get_camera_property_info(p)['has_auto_mode'] == 1:
                cam.set_camera_property(p,cam.get_camera_property(p)[0],1) #set to auto mode
                if cam.get_camera_property_info(p)['name'] == 'shutter':
                    shp = p #shutter property number
                    sh = cam.get_camera_property_info(p)['max_value']
        start_time = time.time()
        while time.time() < start_time + 1: # take frames for a second
            try:
                cam.grab_next_frame_blocking()
                sh = min(sh,cam.get_camera_property(shp)[0]) # find minimum shutter
            except cam_iface.FrameDataCorrupt:
                print "corrupt frame"
                continue
        if camera_properties == 'onepush':
            for p in range(num_props):
                if cam.get_camera_property_info(p)['has_auto_mode'] == 1:
                    if p == shp:
                        cam.set_camera_property(p,sh,0)
                        cam.set_camera_property(p,int(sh/2),0) # set shutter to half minimum in test period
                    else:
                        cam.set_camera_property(p,cam.get_camera_property(p)[0],0)
                        cam.set_camera_property(p,cam.get_camera_property(p)[0],0)
                    
    for p in range(num_props):
        if cam.get_camera_property_info(p)['has_auto_mode'] == 1:
            print "%s = %d, auto = %s"%(cam.get_camera_property_info(p)['name'],cam.get_camera_property(p)[0],bool(cam.get_camera_property(p)[1]))
        else:
            print "%s = %d"%(cam.get_camera_property_info(p)['name'],cam.get_camera_property(p)[0])
            
    
    start_time = time.time()
    frametick = 0
    framecount = 0
    last_fps_print = start_time
    last_fno = None
    while 1:
        try:
            buf = nx.asarray(cam.grab_next_frame_blocking())
        except cam_iface.FrameDataMissing:
            sys.stdout.write('M')
            sys.stdout.flush()
            continue
        except cam_iface.FrameSystemCallInterruption:
            sys.stdout.write('I')
            sys.stdout.flush()
            continue

        timestamp = cam.get_last_timestamp()
        now = time.time()
        fno = cam.get_last_framenumber()
        if last_fno is not None:
            skip = (fno-last_fno)-1
            if skip != 0:
                print 'WARNING: skipped %d frames'%skip
    ##    if frametick==50:
    ##        print 'sleeping'
    ##        time.sleep(10.0)
    ##        print 'wake'
        last_fno=fno
        
        sys.stdout.write('.')
        sys.stdout.flush()
        frametick += 1
        framecount += 1

        t_diff = now-last_fps_print
        if t_diff > 5.0:
            if not low_framerate_mode:
                fps = frametick/t_diff
            else:
                fps = 1.0/ifi
            print "%.1f fps"%fps
            last_fps_print = now
            frametick = 0
            
        if use_comp_time:
            use_timestamp = now
        else:
            use_timestamp = timestamp
            
        if save:
            if not low_framerate_mode:
                save_queue.put( (buf,use_timestamp) )
            elif now - last_time >= 1.0/framerate - .5/actual_framerate:
                save_queue.put( (buf,use_timestamp) )
                ifi = now - last_time
                last_time = now

        if max_frames:
            if framecount >= max_frames:
                print "\n"
                break
                
        if run_time:
            if now - start_time >= run_time:
                print "\n"
                break
      
if __name__=='__main__':
    main()
