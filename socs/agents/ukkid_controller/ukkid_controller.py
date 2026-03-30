import time
import txaio
# For json formatting of status strings.
import json
import sys
import subprocess
import os
import signal
import pdb
import numpy as np
import glob
import re
import shutil

# Set to True to run without RFSoc hardware i.e. in simulated mode for testing.
mock = False

from os import environ

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# JL: append the parent directory to the path so we can import the readout_client module
souk_readout_tools_path = '/home/leechj/souk_readout_tools/src/souk_readout_tools/client/'
sys.path.append(souk_readout_tools_path)

if mock:
    import mock_readout_client as readout_client
else:
    import readout_client

# These modules should be present in souk_readout_tools_path...    
import res_fns
from resonator_fitter import interactive_fit_viewer, fit_summary_table, fit_summary_plot, fit_resonator,fit_summary_histograms,fit_summary_write_json

client = readout_client.ReadoutClient(config_file='config.yaml')
# Push the configuration file above to the RFSoc before attempting anything else.
client.push_config()
    
class UKKIDController:
    """Controller object for streaming data from and sending commands to UK KID RFSoc readout boards.

    Parameters:
        agent (OCSAgent): OCSAgent object from :func:`ocs.ocs_agent.init_site_agent`.

    Attributes:
        agent (OCSAgent): OCSAgent object from :func:`ocs.ocs_agent.init_site_agent`.
        log (txaio.tx.Logger): Logger object used to log events within the
            Agent.
        lock (TimeoutLock): TimeoutLock object used to prevent simultaneous
            commands being sent to hardware.
        JL: Add attribute documentation here.
    """

    def __init__(self, agent,args):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self._check_state = False

        self.kid_stream_id = args.kid_stream_id
        # JL: This needs to eventually come from
        # an agent command line parameter
        # or be set in some config file somewhere.
        # Output data files and directories will be written below this directory.
        self.top_level_output_dir ='/home/leechj/souk_readout_tools/src/souk_readout_tools/client/client_scripts/tmp/'
        # Create this dir if it doesn't exist.                                                                                                                                                                                                                                 
        isExist = os.path.exists(self.top_level_output_dir)
        if not isExist:
           os.makedirs(self.top_level_output_dir)

        # Register OCS feed        
        # JL: Need to register feed names here.
        # Not sure what, if anything, needs to go here
        # just make one called UKKID_feed for the time being
        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('UKKID_feed',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1.)

    # JL: This is a private helper function to determine which directory we should be working in from
    # the supplied "now" time object (returned from time.time() and self.kid_stream_id
    # Returns a tuple with the full path to the working directory and also the path relative to
    # self.top_level_output_dir
    def _create_return_working_directory(self,time_object):
              now_string = str(int(time_object))
              five_digit_ctime = now_string[0:5]
              # Create output directory called five_digit_ctime if it does not already exist
              out_dir = self.top_level_output_dir+'/'+five_digit_ctime
              try:
                  os.mkdir(out_dir)
              except FileExistsError:
                  pass
              else:
                  self.log.info("Created dir "+out_dir )

              # Create output directory five_digit_ctime/kid_stream_id, if it does not already exist
              out_dir = self.top_level_output_dir+'/'+five_digit_ctime+'/'+self.kid_stream_id
              try:
                  os.mkdir(out_dir)
              except FileExistsError:
                  pass
              else:
                  self.log.info("Created dir "+out_dir )
              out_rel_path = five_digit_ctime+'/'+self.kid_stream_id   
              return out_dir, out_rel_path
          
    def check_state(self, session, params):
        """

        **Process** - Continuously checks the current state of the RFSoC. This
        will not modify the RFSoC state, so this task can be run in conjunction
        with other RFSoC operations. This will continuously poll UKKID metadata
        and update the ``session.data`` object.
       
        Gets the state by calling client.get_server_status()  
 
        Args
        ----

        None.
 
        Notes
        -------
        The following data will be written to the session.data object::

            >> response.session['data']
            {
            JL: Insert reasonable stuff here
            }

        """
        with self.lock.acquire_timeout(timeout=0, job='check_state') as acquired:
            if not acquired:
                print("Lock could not be acquired because it "
                      + f"is held by {self.lock.job}")
                return False

            # Initialize last release time for lock
            last_release = time.time()
            self._check_state = True
            self.log.info("Started UKKID check_state process.")

            # Main process loop
            # JL: Set it so this main process releases the lock every 1 second, so that task can be run.
            # Experiments show that if the timeout below is set to a shorter time than an
            # overriding tasks takes, the timeout happens and you get crash e.g.
            # 1746553551.136 CRASH: [Failure instance: Traceback: <class 'RuntimeError'>: release unlocked lock
            # So set the longest_subtask_duration to greater than the longest ever overiding task
            # e.g. likely to be the stream task.
            # No stream should be longer than, say, 12 hours so set to this
            longest_subtask_duration = 12*60*60
            while self._check_state:
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=longest_subtask_duration):
                        print(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False
                    
                self.log.info("Checking status...")

                # JL: Below we add the same json status string to both
                # (1) the UKKID_feed (which you need to subscribe to or look at using the
                # ocs-client-cli listen observatory.UKKIDController1.feeds.UKKID_feed
                # command line line tool
                # and
                # (2) also the "session data" accessed by looking at
                # client.check_state.status().session['data']
                # from within the python agent interface
                #  - not sure if this is appropriate - depends on the intended use of "session" data.
                #
                # In general seems to be 3 places you can send things
                # 1) to the logs (via) self.log.info
                # 2) to the main agents feed e.g. UKKID_feed
                # 3) to the the  "session data"
                #
                # TODO: Decide which data are appropriate to send where.

                now = time.time()
                full_status = client.get_server_status()
                # JL: Maybe thin the content down here, before sending to feed.
                json_status = json.dumps(full_status)

                session.data = {"value": json_status,
                               "timestamp": now}

                # Format message for publishing to Feed
                message = {'block_name': 'status_string',
                          'timestamp': now,
                          'data': {'value': json_status}}

                self.agent.publish_to_feed('UKKID_feed', message)
                time.sleep(1)
                self.agent.feeds['UKKID_feed'].flush_buffer()

        return True, "Finished checking state."

    def _stop_check_state(self, session, params):
        if self._check_state:
            self._check_state = False
            return True, 'requested to stop checking state.'
        else:
            return False, 'check_state is not currently running.'
            
    # Sends a client.get_system information() call to the RF Socs.
    def get_system_information(self, session, params=None):
        """

        **Task** - Gets system information from the RFSocs.

        Args:
            None

        Notes:
          Will call client.get_system information()   
          Should be a quick task so does not needs its own aborter.

        """
        with self.lock.acquire_timeout(timeout=3.0, job='get_system_information') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("Getting RFSoc system information...")

            now = time.time()
            full_status = client.get_server_status()
            json_status = json.dumps(full_status)

            # Write result string to session.data, the feed and the log.
            session.data = {"value": json_status,
                           "timestamp": now}

            # Format message for publishing to Feed
            message = {'block_name': 'status_string',
                      'timestamp': now,
                      'data': {'value': json_status}}
            self.agent.publish_to_feed('UKKID_feed', message)

            self.log.info(full_status)
            time.sleep(1)

            return True, 'Obtained RFSoc system information.'

   # Sends a client.get_initialise_server() call to the RFsocs.
    def initialise_server(self, session, params=None):
        """

        **Task** - Send initialise_server message to the server on the RFSocs

        Args:
            None

        Notes:
          Will call client.initialise_server()
          (or send mock string(s)). 
          Should be a quick task so does not needs its own aborter.

        """
        with self.lock.acquire_timeout(timeout=3.0, job='intialise_server') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("Sending RFSoc initialise_server...")

            now = time.time()
            full_status = client.initialise_server()
            json_status = json.dumps(full_status)
            # JL: This returns a string that looks like this
            # '{"status": "success"}'
            # However,  we get errors like this 
            # 2025-10-10T15-49-40.369218 Unable to format event {'log_logger': <Logger 'ocs.ocs_agent.OCSAgent'>, 'log_level': <LogLevel=info>, 'log_namespace': 'ocs.ocs_agent.OCSAgent', 'log_source': None, 'log_format': 'INITIALISE SERVER RETURNED JSON2:{"status": "success"}', 'log_time': 1760111380.36913, '                  #  message': (), 'time': 1760111380.36913, 'system': '-', 'format': '%(log_legacy)s', 'log_legacy': <twisted.logger._stdlib.StringifiableFromEvent object at 0x7aa852373c10>, 'isError': 0}: '"status"'

            # if we send either { or } characters in the string for the log.
            # So create this stripped version
            json_status_stripped =  json_status.replace('{','').replace('}','')
            # Seems to be okay (I assume) for the feed and the session data though


            # Write result string to session.data, the feed and the log.
            # Note, this also seems to turn up in the log.
            session.data = {"value": json_status,
                           "timestamp": now}

            # Format message for publishing to Feed
            message = {'block_name': 'status_string',
                      'timestamp': now,
                      'data': {'value': json_status}}
            self.agent.publish_to_feed('UKKID_feed', message)

            # Send stripped version to log. 
            self.log.info('initialise_server returned: '+ json_status_stripped)                   
            time.sleep(1)
                    
            return True, 'Sent initialise_server message to RFSocs'

   
    @ocs_agent.param("filename", default=None, type=str)
    @ocs_agent.param("f_guess_filename", default=None, type=str) 
    @ocs_agent.param("f_guess_list", default=None, type=list) 
    def det_res_freq_from_sweep_data(self, session, params=None):
        """

        **Task** - Determines accurate resonant frequencies from wideband sweep data + freq. guesses

        Args:
        "filename", default=None, type=str             # Filename for the input wideband sweep .csv. file. If none supplied, will use latest available in the working dir.
        f_guess_filename", default=None, type=str      # Filename for .json file containing the resonator frequency gueses. If none supplied, will use latest available in the working dir.
        "f_guess_list", default=None, type=list        # Optionally supply a list of resonant frequency guesses, rather than picking up from a file     
        Notes:

        Determines accurate resonant frquencies from wideband sweep data + freq. guesses.    
        Takes output file from a wideband sweep, together with
        a resonator frequency guess file (or direct array) and
        does a more accurate determination of the current resonator frequencies.
        Resonator frequency guess files have file formats like res_freq_guess_ufm_kid1_1760716304.json
        And can be determined from previous RFSoC sweeps are hand determined by e.g. VNA measurements.
        Accurate resonances will be found if there is clear resonance minimum in a window of full width
        window_width (set below) around the individual resonator frequency guesses. 
        Will use the res_fns.py module for the time being to find the more accurate resonant frequency minima.
          
        """
        with self.lock.acquire_timeout(timeout=3.0, job='det_res_freq_from_sweep_data') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("Determining accurate resonant frequencies from wideband sweep data.")

            window_size = 2.0e6 # Full width of window in Hz. Will need to tweak depending on reosnaotr seperation in test array.
            now = time.time()
            (out_full_path, out_rel_path) = self._create_return_working_directory(time.time())

            # If no filename (or value array is available, fail gracefully).
            f_guess_list = None  
            if params['f_guess_list'] is not None:
                # Check if an explicit guess array has been supplied in the arguments. If so, use this, don't look for files elsewhere 
                f_guess_list = params['f_guess_list']
            elif params['f_guess_filename'] is not None:
                # Check if a guess filename has been has been supplied.
                # If yes, Use user supplied filename
                f_guess_filename = self.top_level_output_dir+ params['f_guess_filename']
            else:
                # if not, find latest available filename in all in the top level directory.
                # Filename should have correct naming scheme i.e. beginning res_freq_guess_<self.kid_stream_id>_<10-digit-unix-time>.json
                prefix = 'res_freq_guess_'+self.kid_stream_id
                found_files = glob.glob(self.top_level_output_dir+prefix+'*.json')
                if not found_files:
                   f_guess_filename = None
                else:
                   found_files.sort()
                   f_guess_filename= found_files[-1]

                # If we have found no suitable filename, throw error and return at this point.
                if f_guess_filename is None:    
                   error_msg = 'No .json file with filename '+prefix+'*.json found within directory '+ self.top_level_output_dir
                   self.log.error(error_msg)
                   session.data = {"value": error_msg ,
                           "timestamp": now}
                   message = {'block_name': 'det_res_freq_from_sweep_data_string',
                      'timestamp': now,
                      'data': {'value': error_msg }}
                   return False, error_msg

            if f_guess_list is None:
               # We are not using a user supplied list, so
               # try opening the file f_guess_filename   
               try: 
                    with open(f_guess_filename) as f:
                       d = json.load(f)
                       f_guess_list =  d['f_guess_list']
               except json.decoder.JSONDecodeError:
                    error_msg = 'Problem with decoding json file: ' + params['f_guess_filename']
                    self.log.error(error_msg)
                    session.data = {"value": error_msg ,
                           "timestamp": now}
                    message = {'block_name': 'det_res_freq_from_sweep_data_string',
                      'timestamp': now,
                      'data': {'value': error_msg }}
                    return False, error_msg
               except KeyError:
                    error_msg = 'Expected key f_guess_list not found in json file: ' + params['f_guess_filename']
                    self.log.error(error_msg)
                    session.data = {"value": error_msg ,
                           "timestamp": now}
                    message = {'block_name': 'det_res_freq_from_sweep_data_string',
                      'timestamp': now,
                      'data': {'value': error_msg }}
                    return False, error_msg
                
               self.log.info('Guess Frequencies extracted from '+f_guess_filename)

            # At this point. f_guess_list should defined - send to log.
            self.log.info('Found guess frequencies of ' +str(f_guess_list))

            if params['filename'] is None:
                # We need to find the most recent file matching <10-digit-unix-time>_full_band_sweep.csv
                # (File format may (or may noe) get changed from .csv to .g3 at some point
                #
                files = [os.path.join(dirpath, filename)
                      for (dirpath, dirs, files) in os.walk(self.top_level_output_dir)
                      for filename in (dirs + files)]

                # Get only the files which have full_band_sweep.csv as a substring
                the_csv_full_paths = [x for x in files if 'full_band_sweep.csv' in x]
                # Sort by the filename (after the last '/' character) - effectively sorts by <10-digit-unix-time>
                the_csv_full_paths.sort(key=lambda item: item.split('/')[-1])
                # Get the last element, which will be the most recently taken full_band_sweep
                sweep_filename = the_csv_full_paths[-1]
            else:
                sweep_filename = params['filename']

            self.log.info('Will use full band sweep filename ' + sweep_filename)
            # The column descriptor line begins with the word "sweep", so use 's' as well as '#' as a comment character.
            x, i, q = np.loadtxt(sweep_filename, delimiter =',', usecols =(0, 1, 2), comments=['#','s'], unpack = True) 
            accurate_res = res_fns.find_all_resonances(x,i,q,f_guess_list,window_size)
            self.log.info('Using guess frequencies of ' +str(f_guess_list))
            self.log.info('Found more accurate frequencies of ' +str(accurate_res.tolist()))

            # Write out to a json formatted file with filename res_freq_accurate_<10-digit-unix-time>.json
            f_acc_dict = {'f_accurate_list': accurate_res.tolist() }
            now = time.time()

            out_json_fname = out_full_path+'/'+'res_freq_accurate_'+self.kid_stream_id+'_'+str(int(now))+'.json'
            self.log.info('Accurate resonant frequencies will be written out out to file '+  out_json_fname)
            with open(out_json_fname, 'w', encoding='utf-8') as f:
               json.dump(f_acc_dict, f, ensure_ascii=False, indent=4)
            self.log.info('Accurate resonant frequencies written out to file '+  out_json_fname)

            # Finally send data out to feed
            feed_string = 'Guess freqs: ' + str(f_guess_list)+' Accurate Freqs: '+ str(accurate_res.tolist())
            now = time.time()
            session.data = {"value": feed_string,
                            "timestamp": now}

            # Format message for publishing to Feed
            message = {'block_name': 'det_res_freq_from_sweep_data_string',
                       'timestamp': now,
                        'data': {'value': feed_string}}
            self.agent.publish_to_feed('UKKID_feed', message)

            time.sleep(4)
            self.agent.feeds['UKKID_feed'].flush_buffer()
            
            return True, '"Determined accurate resonant frequencies from wideband sweep data.'
        
    @ocs_agent.param("filename", default=None, type=str) 
    def fit_from_narrow_sweep(self, session, params=None):
        """

        **Task** -Takes the output .csv file from a narrow_band_sweep and fits resonator parameters. Using functions
        from the fit_resonator.py module.

        Args:
            
        filename: Filename for the narrow_band sweep .csv file. If none supplied, will use latest available.

        Notes:
          
        """
        with self.lock.acquire_timeout(timeout=3.0, job='fit_from_narrow_sweep') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("Fitting resonator parameters from narrow band sweep data.")
            
            now = time.time()
            (out_full_path, out_rel_path) = self._create_return_working_directory(time.time())

            if params['filename'] is None:
                # We need to find the most recent file matching <10-digit-unix-time>_full_band_sweep.csv
                # (File format may get changed to .g3 at some point
                files = [os.path.join(dirpath, filename)
                      for (dirpath, dirs, files) in os.walk(self.top_level_output_dir)
                      for filename in (dirs + files)]

                # Get only the files which have full_band_sweep.csv as a substring
                the_csv_full_paths = [x for x in files if 'narrow_band_sweep.csv' in x]
                # Sort by the filename (after the last '/' character) - effectively sorts by <10-digit-unix-time>
                the_csv_full_paths.sort(key=lambda item: item.split('/')[-1])
                # Get the last element, which will be the most recently taken full_band_sweep
                sweep_filename = the_csv_full_paths[-1]
            else:
                sweep_filename = out_full_path+'/'+ params['filename'] 
  

            self.log.info('Will use narrow band sweep filename ' + sweep_filename)
            self.log.info('Importing sweep data...')
            s=client.import_sweep(sweep_filename)
            self.log.info('...done.')

            f,z,e = s['sweep_f'], s['sweep_i']+1j*s['sweep_q'], s['sweep_ei']+1j*s['sweep_eq']

            self.log.info('Fitting resonator parameters...')
            fit_results = [fit_resonator(f[:,i],z[:,i],
                                         sweep_direction='up',
                                         mag_order=1,phase_order=1,
                                         use_preconditioning=1,verbose=False) for i in range(len(f[0]))]
            self.log.info('...done.')

            now_string = str(int(now))

            self.log.info('Generating plots...')
            fit_results = interactive_fit_viewer(f.T, z.T, fit_results=fit_results,show_preconditioned=1,interactive =False,output_dir=out_full_path,now_string=now_string)
            self.log.info('...done.')

            # JL TODO - makes this a json file.
            self.log.info('Generating summary table...') 
            outfilename = out_full_path+'/'+'fit_summary_table_'+self.kid_stream_id+'_'+now_string +'.txt'
            table_str, summaries, filename = fit_summary_table(
                fit_results, 
                outfilename=outfilename
            )
            self.log.info('...done.')

            # JL TODO - makes this a json file.
            self.log.info('Generating summary .json file...') 
            outfilename = out_full_path+'/'+'fit_summary_json_'+self.kid_stream_id+'_'+now_string +'.json'
            fit_summary_write_json(
                fit_results, 
                outfilename=outfilename
            )
            self.log.info('...done.')


            self.log.info('Generating summary plot...') 
            outfilename = out_full_path+'/'+'fit_summary_plot_'+self.kid_stream_id+'_'+now_string+'.png'
            fig, axes, plotfile = fit_summary_plot(
                fit_results,
                outfilename=outfilename
            )
            self.log.info('...done.')

            self.log.info('Generating histogram plots...')
            outfilename = out_full_path+'/'+'fit_histogram_plot_'+self.kid_stream_id+'_'+now_string+'.png'
            fig_hist, axes_hist, histfile = fit_summary_histograms(
                fit_results,
                xscale_for={'Qi':'log', 'Qc':'log', 'Nonlinearity':'log'},
                outfilename=outfilename
            )
            self.log.info('...done.')
            time.sleep(4)
            self.agent.feeds['UKKID_feed'].flush_buffer()
            
            return True, '"Determined resonator parameters from narrow band sweep data.'

        
    
    @ocs_agent.param("duration", default=30, type=float) # JL 30 seconds is default stream time - useful for test/debugging. In practice, will be manually set in co-ordination with expected ACU scan time. 
    def stream(self, session, params=None):
        """

        **Task** - Streams IQ data from the RFSocs.

        Args
        -----
        duration : float, optional
            If set, determines how many seconds to stream data. Default is 30 seconds (for debug). 
        """
        
        with self.lock.acquire_timeout(timeout=3.0, job='stream') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("Streaming RFSoc system information...")
            self.log.info("kid_stream_id: " + self.kid_stream_id)
            
            stream_start_time = time.time()
 
            # Check how many tone frequencies are currently set, to pass to the receive_stream_g3.py below.
            tone_freqs = client.get_tone_frequencies()
            num_freqs = len(tone_freqs)
            
            self.log.info("Enabling stream on RFSoc board.")
            client.enable_stream()              
            self.log.info("Starting stream receive process.")

            (out_full_path, out_rel_path) = self._create_return_working_directory(time.time())    
            now_string = str(int(stream_start_time))
            # Make an output filename string
            # JL: Not exactly sure what the observatory policy on setting this is - hardwiring to '000' for the time being.
            three_digit_file_count ='000'
            output_stream_filename = now_string+'_'+three_digit_file_count+'.g3'
            output_stream_relative_path = out_rel_path + '/'+output_stream_filename
            output_stream_full_path = out_full_path + '/'+output_stream_filename
            self.log.info("Will stream data to file: "+output_stream_relative_path)
 
            if mock:
               mock_flag = "T" 
            else:
               mock_flag = "F" 
            
            executable_list = [sys.executable, "receive_stream_g3.py","-m",mock_flag,"-n",str(num_freqs),"-f",output_stream_relative_path]
            executable_string = " ".join(executable_list)
            self.log.info("Launching stream task " + executable_string)
            
            p=subprocess.Popen(executable_list,cwd=souk_readout_tools_path+'/client_scripts/',stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)

            self.log.info("stream receive process pid is " + str(p.pid))
            
            # Communicate with the process for 2 seconds
            # long enough for the process to send any obvious errors to stderr / stdout
            try:
              output, errors = p.communicate(timeout=2)
            except:
             self.log.info("Stream receive process communication reached timeout limit, as expected, continuing...")
             # JL: Best way to do this?
            if 'output' in locals():   
              self.log.info("stream receive process STDOUT: " + output)
            if 'errors' in locals(): 
              self.log.info("stream receive process STDERR: "+ errors)
          
            now = time.time()
            
            # Now just go into a loop to wait out the streaming duration timme
            while((now - stream_start_time) < params['duration']):
             now = time.time()
             steam_active_seconds = (now - stream_start_time)

             # Check it is still running,
             process_died = False
             if p.poll() is None:
                if os.path.exists(output_stream_full_path): 
                  file_size = os.path.getsize(output_stream_full_path)
                else:
                  file_size = -1

                if file_size !=-1:
                  stream_status_string = "Data has been streaming for %.1f seconds, output file size = %i KB" % ((now - stream_start_time),file_size/1024)
                else:
                  stream_status_string = "Data has been streaming for %.1f seconds, no output file exists yet."  % (now - stream_start_time)
                  
             else:
                stream_status_string = "WARNING streaming process finished unexpectedly at %.1f seconds." % (now - stream_start_time)
                process_died = True
                
             session.data = {"value": stream_status_string,
                        "timestamp": now}

             # Format message for publishing to Feed
             message = {'block_name': 'stream_string',
                    'timestamp': now,
                     'data': {'value': stream_status_string}}
             self.agent.publish_to_feed('UKKID_feed', message)

            
             # Also send this string to the log - discuss wether appropriate.
             if not process_died:  
               self.log.info(stream_status_string)
             else:
               self.log.error(stream_status_string)
             time.sleep(2)
             now = time.time()
                  
        # End of time duration loop, disable the stream, and terminate the strea,ing process.
        self.log.info("Disabling stream on RFSoc board.")
        client.disable_stream()
        
        self.log.info("Sending SIGTERM to recieve process...")
        try:
            os.kill(p.pid, signal.SIGTERM)
            
        except OSError as e:
             self.log.error("Error received from os.kill:")
             self.log.error(f"Failed to send signal: {os.strerror(e.errno)}")
             
        self.log.info("... done.")
        
        self.log.info("Streaming RFSoc duration expired.") 
        self.log.info("Returning from stream function.")
        message = {'block_name': 'stream_string',
                    'timestamp': now,
                     'data': {'value': "Streaming complete"}}

        self.agent.publish_to_feed('UKKID_feed', message)
        
        # JL: Presumably,I should return False here if process_died error or Error received from os.kill?
        return True, 'Streamed RFSoc data.'

    def _abort_stream(self, session, params):
          if session.status == 'running':
             session.set_status('stopping')

          if session.status != 'running':
             return False, 'Aborted streaming RFSoc data.'



    # Task to perform a wideband sweep across the full RF bandwidth.
    @ocs_agent.param("filename", default=None, type=str)
    @ocs_agent.param("bandwidth_hz", default=None, type=float)
    @ocs_agent.param("center_freq_hz", default=None, type=float)
    @ocs_agent.param("step_size_hz", default=10000, type=int)
    @ocs_agent.param("num_tones", default=1024, type=int)
    @ocs_agent.param("samples_per_point", default=10, type=int)
    @ocs_agent.param("ignore_phase_correction", default=False, type=bool)
    @ocs_agent.param("plot_data", default = True, type = bool)
    @ocs_agent.param("tone_amplitude", default=0.2, type=float)
    def full_band_sweep(self, session, params=None):
        """

        **Task** - Performs a wideband sweep across the full RF bandwidth.

        Args
        ----
        "filename", default=None, type=str,  -- Output filename for sweep data. If none supplied, will auto-generate a filename.
        "bandwidth_hz", default=None, type=float, --  Bandwidth to sweep over in Hz. If none supplied, will use the whole RF band (rfmax-rfmin).
        "center_freq_hz", default=None, type=float -- Centre frquency for sweep in Hz. If none supplied, will use the full RF band centre (rfmax+rfmin)/2
        "step_size_hz", default=10000, type=int, -- Step size for the scan, in Hz. Default is 10 kHz.
        "num_tones", default=1024, type=int -- Number of simultaneous probe tones that will be used in the scan. Default is 1024.
        "samples_per_point", default=10, type=int, -- Number of samples taken at each frequency point. Default is 10. Adding more may reduce noise, but lead to 
                                                      longer scans (with the defaults,  current takes about 43 seconds to scan).
        "ignore_phase_correction", default=False, type=bool -- Set to true to ignore the phase correction.
        "plot_data", default = True, type = bool  -- Make a .png plot of the S21 amplitude and phase of the scan. Default = True.      
        "tone_amplitude", default=0.2, type=float -- Amplitude of each tone used on the scan, relative to RFSoCs DAC full-scale-deflection.

        """
        #################################
        # TO DO
        # 
        # Amplitiude setting - hardwired at the moment
        #
        # Think about whether we need to send more stuff to the ukkidcontroller feed as opposed to just the log.
        #
        
        with self.lock.acquire_timeout(timeout=3.0, job='full_band_sweep') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("full_band_sweep: Preparing to perform a full band sweep for: kid_stream_id: " + self.kid_stream_id)
            
            plot_data = params['plot_data']
            sweep_start_time = time.time()
            filetype='csv'
            
            (out_full_path, out_rel_path) = self._create_return_working_directory(time.time())
            now_string = str(int(sweep_start_time))
            # Make an output filename string
            if params['filename'] is None:  
               output_sweep_filename = now_string+'_'+'full_band_sweep'+'.csv'
            else:
               output_sweep_filename = params['filename']
               
            output_sweep_full_path = out_full_path + '/'+output_sweep_filename
            
            if not mock:
              self.log.info("full_band_sweep: Will write sweep data to " + output_sweep_full_path)
            else:
              # Copy an example sweep file over to the output destination, then return from the function, without doing any real scan on the RFSoC.  
              self.log.info("full_band_sweep: MOCKED - Will write sweep data to " + output_sweep_full_path)              
              loop_time_seconds = 10.0
              
              shutil.copy('./example_full_band_sweep.csv',output_sweep_full_path)
              self.log.info("full_band_sweep: sweep data written to " + output_sweep_full_path)
              if plot_data:  
               plot_filename =  output_sweep_full_path.replace(filetype,'')+'png'
               shutil.copy('./example_full_band_sweep.png',plot_filename)
               self.log.info("full_band_sweep: sweep data PNG file written to " + plot_filename)

              now = time.time()            
              # Now just go into a loop to wait out the sweep time
              while((now - sweep_start_time) < loop_time_seconds ):
               now = time.time()
               sweep_active_seconds = (now - sweep_start_time)
               sweep_status_string = "Data has been sweeping for %.1f seconds." % (now - sweep_start_time)
                 
               session.data = {"value": 'SESSION ' + sweep_status_string,
                            "timestamp": now}

               # Format message for publishing to Feed
               message = {'block_name': 'sweep_string',
                    'timestamp': now,
                     'data': {'value': 'FEED '+ sweep_status_string}}
               self.agent.publish_to_feed('UKKID_feed', message)
              
               # Also send this string to the log - discuss whether appropriate.
               self.log.info('LOG' + sweep_status_string) 
               time.sleep(1)
               now = time.time()
               self.log.info('full_band_sweep: MOCKED Sweep complete.')
               return True, 'full_band_sweep: MOCKED Sweep complete.'

            # Rest is for REAL, non-mocked case.
            # Firstly, check if a sweep is already in progress on the RFSoC.
            # It shouldn't be, but throw an error and return from function if there is.
            now = time.time() 
            p = client.get_sweep_progress()
            if p==0.0:
               pass
            elif p != 1.0:
               # Send error message to feed, and log and return from function with error state.  
               stream_in_progress_error_msg = f'full_band_sweep: There is already a sweep in progress ({p*100:.3f}%), please wait for it to finish before starting a new one.'
               self.log.error(stream_in_progress_error_msg)
               session.data = {"value": stream_in_progress_error_msg ,
                                   "timestamp": now}                    
               message = {'block_name': 'status_string',
                              'timestamp': now,
                              'data': {'value':  stream_in_progress_error_msg }}
               self.agent.publish_to_feed('UKKID_feed', message)  
               self.agent.feeds['UKKID_feed'].flush_buffer()
               
               return False, stream_in_progress_error_msg 
             

            # Gather certain parameters from the RFSoc in order to calculate
            # sweep parameters.
            client.pull_config()
            info = client.get_system_information()
            adcclk = info['adc_clk_hz']
            dacclk = adcclk
            dacduc = info['dac_duc_mixer_frequency_hz']
            dacnyq = info['nyquist_zone_dac0']             
            udc = client.config['rf_frontend']['connected']
            lo = client.config['rf_frontend']['tx_mixer_lo_frequency_hz']
            sb = client.config['rf_frontend']['tx_mixer_sideband'] 
            # Hardwired vales - numbe rof bytes per dac data point and fft window sizes.
            
            dacint = 2
            txnfft = 8192
            rxnfft = 8192
            
            dbbmin = -dacclk/2
            dbbmax = +dacclk/2

            dacmin = min([abs(dbbmin+dacduc),abs(dbbmax+dacduc)])            
            dacmax = max([abs(dbbmin+dacduc),abs(dbbmax+dacduc)])
            
            rfmin = dacmin
            rfmax = dacmax

            num_tones = params['num_tones']
            step_size_hz = params['step_size_hz']
            samples_per_point = params['samples_per_point']
            ignore_phase_correction = params['ignore_phase_correction']
            tone_amplitude =  params['tone_amplitude']
            
            try:
                if udc:
                    if sb==1:
                        rfmin = lo + dacmin
                        rfmax = lo + dacmax
                    elif sb==-1:
                        rfmin = lo - dacmax
                        rfmax = lo - dacmin
                    else:
                        raise ValueError(f"full_band_sweep: Invalid sideband value {sb}, should be +1 for USB or -1 for LSB")

                if params['bandwidth_hz'] is None:
                    bandwidth_hz=rfmax-rfmin
                else:
                    bandwidth_hz=params['bandwidth_hz']    

                if params['center_freq_hz'] is None:
                    center_freq_hz = (rfmax+rfmin)/2
                else:    
                    center_freq_hz = params['center_freq_hz']

                fmin = center_freq_hz - bandwidth_hz/2
                fmax = center_freq_hz + bandwidth_hz/2

                if (fmin < rfmin) or (fmax>rfmax):
                        raise ValueError(f'full_band_sweep: Attempting to sweep out of band (band = {rfmin/1e6} - {rfmax/1e6} MHz, requested {fmin/1e6} - {fmax/1e6} MHz)')


                freqs,spacings = np.linspace(fmin, fmax, num_tones, endpoint=False, retstep=True)

                if spacings <= dacclk/txnfft:
                    raise ValueError(f'full_band_sweep: Tone spacing must be greater than {dacclk/txnfft} Hz but it is {spacings}. Try fewer tones or wider bandwidth.') 

                # sweep_points = 41 # not too many as its currently quite slow
                sweep_points = int(bandwidth_hz / step_size_hz / num_tones) 
                sweep_span = spacings * (sweep_points-1)/(sweep_points)

                # np.random.seed(0)
                # small_offsets = np.random.uniform(-sweep_span/sweep_points/20,+sweep_span/sweep_points/20,num_tones) # the offsets is less than 10% of the step size
                small_offsets = np.random.uniform(-sweep_span/sweep_points/2,+sweep_span/sweep_points/2,num_tones) # the largest combined offset is <= 100% of the step size
                # small_offsets = np.around(small_offsets) # round to nearest integer
                freqs += small_offsets


                center_freqs = freqs + np.floor(sweep_points/2)*spacings/sweep_points
                tone_amplitudes = np.ones(num_tones)*tone_amplitude # all set to the same makes sense for e.g. 1024 tone wideband sweeps.
                tone_phases = client.generate_newman_phases(center_freqs)

                param_report_msg = f'full_band_sweep: Supplied parameters center_freq_hz {center_freq_hz} step_size_hz {step_size_hz} num_tones {num_tones} samples_per_point {samples_per_point} ignore_phase_correction {ignore_phase_correction}  plot_data {plot_data}'
                self.log.info(param_report_msg)
                session.data = {"value": param_report_msg ,
                                   "timestamp": now}                    
                message = {'block_name': 'status_string',
                              'timestamp': now,
                              'data': {'value':  param_report_msg }}
                self.agent.publish_to_feed('UKKID_feed', message)  
                self.agent.feeds['UKKID_feed'].flush_buffer()

                param_report_msg = f'full_band_sweep: Full sweep parameters determined as: udc {udc}, lo {lo}, sb {sb}, dacduc {dacduc}, dacclk {dacclk}, dacnyq {dacnyq}, txnfft {txnfft} rxnfft {rxnfft} dacmin {dacmin} dacmax {dacmax} rfmin {rfmin} rfmax {rfmax} bandwidth_hz  {bandwidth_hz}  freqs {freqs} center_freqs {center_freqs}  center_freqs.min() {center_freqs.min()} center_freqs.max() {center_freqs.max()}'
                self.log.info(param_report_msg)
                session.data = {"value": param_report_msg ,
                                   "timestamp": now}                    
                message = {'block_name': 'status_string',
                              'timestamp': now,
                              'data': {'value':  param_report_msg }}
                self.agent.publish_to_feed('UKKID_feed', message)  
                self.agent.feeds['UKKID_feed'].flush_buffer()
                    
            except ValueError as e:
               # Send error message to feed, and log and return from function with error state.  
               value_error_msg = str(e) 
               self.log.error(value_error_msg)
               session.data = {"value": value_error_msg ,
                                   "timestamp": now}                    
               message = {'block_name': 'status_string',
                              'timestamp': now,
                              'data': {'value':  value_error_msg }}
               self.agent.publish_to_feed('UKKID_feed', message)  
               self.agent.feeds['UKKID_feed'].flush_buffer()
               
               return False, value_error_msg
           

            self.log.info('full_band_sweep: Setting tone frequences, ampltiudes and phases on RFSoc.')
            client.set_tone_frequencies(center_freqs)
            client.set_tone_amplitudes(tone_amplitudes)
            client.set_tone_phases(tone_phases)

            self.log.info('full_band_sweep: Checking for input/output ADC/DAC saturation and DSP overflow on RFSoc.')
            
            try:
              outps = client.check_output_saturation()
              inps  = client.check_input_saturation()
              dspof = client.check_dsp_overflow()
    
              if outps['result']:
                raise RuntimeError(f"full_band_sweep: Output saturation detected: {outps['details']}")
              if inps['result']:
                raise RuntimeError(f"full_band_sweep: Input saturation detected: {inps['details']}")
              if dspof['result']:
                raise RuntimeError(f"full_band_sweep: DSP overflow detected: {dspof['details']}")

            except RuntimeError as e:
               # Send error message to feed, and log and return from function with error state.
               # Sending with error strings with curly brackets in them seems to cause errors like this.
               # Unable to format event {'log_logger': <Logger 'ocs.ocs_agent.OCSAgent'>, 'log_level': <LogLevel=error>, 'log_namespace': 'ocs.ocs_agent.OCSAgent', 'log_source': None, 'log_format': '"full_band_sweep: Output saturation detected: {\'i0max_fs\': 0.99676513671875, \'i0min_fs\': -0.996124267578125, \'q0max_fs\': 0.99639892578125, \'q0min_fs\': -0.99737548828125, \'i1max_fs\': 0.0, \'i1min_fs\': 0.0, \'q1max_fs\': 0.0, \'q1min_fs\': 0.0, \'integration_time\': 2e-05, \'threshold\': 0.95}"', 'log_time': 1772129919.5274072, 'message': (), 'time': 1772129919.5274072, 'system': '-', 'format': '%(log_legacy)s', 'log_legacy': <twisted.logger._stdlib.StringifiableFromEvent object at 0x701bb8a44b50>, 'isError': 1}: "'i0max_fs'"  
               # Following fixes this. 
               runtime_error_msg = repr(str(e))
               runtime_error_msg =runtime_error_msg.replace('{','').replace('}','')
               
               self.log.error(runtime_error_msg)
               session.data = {"value": runtime_error_msg ,
                                   "timestamp": now}                    
               message = {'block_name': 'status_string',
                              'timestamp': now,
                              'data': {'value':  runtime_error_msg }}
               self.agent.publish_to_feed('UKKID_feed', message)  
               self.agent.feeds['UKKID_feed'].flush_buffer()
               
               return False, runtime_error_msg

            self.log.info('full_band_sweep: Performing sweep...')

            try:
                response = client.perform_sweep(center_freqs,
                                    sweep_span,
                                    points = sweep_points,
                                    samples_per_point = samples_per_point,
                                    direction = 'up')
    
                if response['status'] != 'success':
                   raise RuntimeError(f"full_band_sweep: Sweep failed with message: {response['message']}")

            except RuntimeError as e: 
                # Send error message to feed, and log and return from function with error state.  
               runtime_error_msg = str(e)
               self.log.error(runtime_error_msg)
               session.data = {"value": runtime_error_msg ,
                                   "timestamp": now}                    
               message = {'block_name': 'status_string',
                              'timestamp': now,
                              'data': {'value':  runtime_error_msg }}
               self.agent.publish_to_feed('UKKID_feed', message)  
               self.agent.feeds['UKKID_feed'].flush_buffer()
               
               return False, runtime_error_msg

            
            while True:
               p=client.get_sweep_progress()
               self.log.info(f'full_band_sweep: Sweep progress: {100*p:.3f}%')
               if p==1.0: break
               else: time.sleep(1.0)

            self.log.info('full_band_sweep: Parsing sweep data ...')
            s = client.parse_sweep_data(client.get_sweep_data(),apply_phase_correction=not ignore_phase_correction)
            f = s['sweep_f']
            z = s['sweep_i']+1j*s['sweep_q']

            # remove slope from phase
            fcat = np.ravel(f.T)
            zcat = np.ravel(z.T)
            phicat = np.angle(zcat)
            slope = np.nanmedian(np.gradient(phicat,fcat))
            zcat *= np.exp(-1j*(slope*fcat))

            s['sweep_f'] = [fcat]
            s['sweep_i'] = [np.real(zcat)]
            s['sweep_q'] = [np.imag(zcat)]
            s['sweep_ei'] = [np.ravel(s['sweep_ei'].T)]
            s['sweep_eq'] = [np.ravel(s['sweep_eq'].T)]

            self.log.info('full_band_sweep: Saving sweep data to disk.')
            client.export_sweep(output_sweep_full_path, s, filetype)
            filename = output_sweep_full_path.replace(filetype,'')+filetype
            self.log.info('full_band_sweep: Fullband sweep exported to:'+filename)
            
            if plot_data:
                error_bars = False
                plot_filename =  output_sweep_full_path.replace(filetype,'')+'png'
                self.log.info('full_band_sweep: Generating quick look plot, writing to ' + plot_filename)                
                sf = s['sweep_f'][0]
                si = s['sweep_i'][0]
                sq = s['sweep_q'][0]
                sz = si+1j*sq
                logmag = 20*np.log10(abs(sz))
                uphase = np.unwrap(np.angle(sz))

                ei = s['sweep_ei'][0] #/ np.sqrt(s['samples_per_point'])
                eq = s['sweep_eq'][0] #/ np.sqrt(s['samples_per_point'])
                emag = 1/abs(sz)*np.sqrt((si*ei)**2 + (sq*ei)**2)
                elogmag = 20/np.abs(sz)/np.log(10)*emag
                ephi = 1/(si**2+sq**2) * np.sqrt((sq*ei)**2+(si*eq)**2)

                import matplotlib.pyplot as plt
                fig,(s1,s2) = plt.subplots(2,1,sharex=True)
                #s1.plot(f/1e6, logmag)
                #s2.plot(f/1e6, uphase)
                if error_bars:
                    s1.errorbar(sf/1e6, logmag, yerr=elogmag, fmt='.', ecolor='red')
                    s2.errorbar(sf/1e6, uphase, yerr=ephi, fmt='.', ecolor='red')
                else:
                    s1.plot(sf/1e6, logmag,linewidth=0.5)
                    s2.plot(sf/1e6, uphase,linewidth=0.5)                    
                fig.supxlabel('Frequency (MHz)')
                s1.set_ylabel('Power (dB)')
                s2.set_ylabel('Phase (rad)')
                s1.set_ylim(np.min(logmag),np.max(logmag))
                s2.set_ylim(np.min(uphase),np.max(uphase))
                plt.savefig(plot_filename,dpi=300) 
                self.log.info('full_band_sweep: Plot saved to ' + plot_filename)
            
            ################################################
              
        self.log.info('full_band_sweep: Sweep complete.')
        #JL: write something to the feed here?
        return True, 'full_band_sweep: Sweep complete.'

    def _abort_full_band_sweep(self, session, params):
          if session.status == 'running':
             session.set_status('stopping')

          if session.status != 'running':
             return False, 'Aborted full band sweep data.'
       
    @ocs_agent.param("filename", default=None, type=str)
    @ocs_agent.param("f_accurate_filename", default=None, type=str)
    @ocs_agent.param("plot_data", default = True, type = bool)
    @ocs_agent.param("tone_amplitude", default=0.2, type=float) 
    @ocs_agent.param("freq_span", default=1.0e6, type=float) 
    @ocs_agent.param("f_accurate_list", default=None, type=list) 
    @ocs_agent.param("num_points", default=2001, type=int) 
    @ocs_agent.param("samples_per_point", default=20, type=int) 
    def narrow_band_sweep(self, session, params=None):
        """

        **Task** - 
          Task to perform a narrow band sweep with tones centred on a supplied list (either in supplied list or a default file)
          across the narrow RF bandwidth sufficient to characterise the profile of each resonator

        Args
        ----
            ----                                                                                                                                                                                                                                                                                                                                                               
        "filename", default=None, type=str,  -- Output filename for sweep data. If none supplied, will auto-generate a filename.
        "f_accurate_filename", default=None, type=str -- Input filename for the .json file containing the previously determined accurate resonator freqeuncies.
                                                         Default behaviour (i.e. with None supplied) is to search for the working directory for the latest version of such a file.
        "plot_data", default = True, type = bool -- Make a .png plot of the S21 amplitude and phase of the scan. Default = True.        
        "tone_amplitude", default=0.2, type=float -- Amplitude of each tone used on the scan, relative to RFSoCs DAC full-scale-deflection.
        "freq_span", default=1.0e6, type=float) --  Sweep span in Hz.                                                                                                                                                                                                                                                                                           
        "f_accurate_list", default=None, type=list) -- List of supplied (accurate) resonator frequencies, if you want to specify these as a python list rather than reading in from a file.                                                                                                                                                                                       "num_points", default=2001, type=int)  --  Number of frequency points within the sweep span window                                                                                                                                                                                                                                                        
        "samples_per_point", default=20, type=int) -- Number of samples to take per frequency point        
        """
        #################################
        # TO DO
        # JL: Amplitiude setting - hardwired at the moment
        # JL: Think about whether we need to send more stuff to the ukkidcontroller feed as opposed to just the log.
        
        with self.lock.acquire_timeout(timeout=3.0, job='narrow_band_sweep') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("narrow_band_sweep: Preparing to perform a narrow band sweep for: kid_stream_id: " + self.kid_stream_id)
            
            plot_data = params['plot_data']
            filetype='csv'            
            (out_full_path, out_rel_path) = self._create_return_working_directory(time.time())
            sweep_start_time = time.time()
            now_string = str(int(sweep_start_time))
            
            # Make an output filename string
            if params['filename'] is None:  
               output_sweep_filename = now_string+'_'+'narrow_band_sweep'+'.csv'
               output_sweep_plot_filename = now_string+'_'+'narrow_band_sweep'+'.png'
            else:
               output_sweep_filename = params['filename']
               output_sweep_plot_filename = params['filename'] +'.png'
               
            output_sweep_narrow_path = out_full_path + '/'+output_sweep_filename
            output_sweep_narrow_plot_path = out_full_path + '/'+output_sweep_plot_filename
            
            if not mock:
              self.log.info("narrow_band_sweep: Will write sweep data to " + output_sweep_narrow_path)
            else:  
              self.log.info("narrow_band_sweep: Will write sweep data to " + output_sweep_narrow_path)
              # Mocked behaviour - test open a file at the file location, send some progress data in a loop_time_seconds
              # Then exit.
        
              loop_time_seconds = 10.0
              # Copy an example sweep file over to the output destination
              # These example files derive from
              # 1763660769_narrow_band_sweep.png
              # and
              # 1763660769_narrow_band_sweep.csv
              shutil.copy('./example_narrow_band_sweep.csv',output_sweep_narrow_path)
              self.log.info("narrow_band_sweep: sweep data written to " + output_sweep_narrow_path)
              if plot_data:  
               plot_filename =  output_sweep_narrow_path.replace(filetype,'')+'png'
               shutil.copy('./example_narrow_band_sweep.png',plot_filename)
               self.log.info("full_narrow_sweep: sweep data PNG file written to " + plot_filename)

              now = time.time()            
              # Now just go into a loop to wait out the sweep time
              while((now - sweep_start_time) < loop_time_seconds ):
               now = time.time()
               sweep_active_seconds = (now - sweep_start_time)
               sweep_status_string = "Data has been sweeping for %.1f seconds." % (now - sweep_start_time)
                 
               session.data = {"value": 'SESSION ' + sweep_status_string,
                            "timestamp": now}

               # Format message for publishing to Feed
               message = {'block_name': 'sweep_string',
                    'timestamp': now,
                     'data': {'value': 'FEED '+ sweep_status_string}}
               self.agent.publish_to_feed('UKKID_feed', message)
              
               # Also send this string to the log - discuss wther appropriate.
               self.log.info('LOG' + sweep_status_string) 
               time.sleep(1)
               now = time.time()
               self.log.info('narrow_band_sweep: Sweep complete.')
               return True, 'narrow_band_sweep: Sweep complete.'

            ########################################################
            # Rest is for REAL case
            # Firstly, check if a sweep is already in progress on the RFSoC.
            # It shouldn't be, but throw an error and return from function if there is.
            now = time.time() 
            p = client.get_sweep_progress()
            if p==0.0:
               pass
            elif p != 1.0:
               # Send error message to feed, and log and return from function with error state.  
               stream_in_progress_error_msg = f'narrow_band_sweep: There is already a sweep in progress ({p*100:.3f}%), please wait for it to finish before starting a new one.'
               self.log.error(stream_in_progress_error_msg)
               session.data = {"value": stream_in_progress_error_msg ,
                                   "timestamp": now}                    
               message = {'block_name': 'status_string',
                              'timestamp': now,
                              'data': {'value':  stream_in_progress_error_msg }}
               self.agent.publish_to_feed('UKKID_feed', message)  
               self.agent.feeds['UKKID_feed'].flush_buffer()
               
               return False, stream_in_progress_error_msg 
             
            ########################################################
            # Check to see if resonator list has been provided
            # on function call, if not,
            # see if an f_accurate_filename has been provided, and use that
            # else use the most recent file that has a filename of format e.g. res_freq_accurate_1761061802.json
            now = time.time()
            f_accurate_list = None
            if params['f_accurate_list'] is not None:
                        # Use user-supplied python list of freqeuncies  
                        f_accurate_list = params['f_accurate_list']
            elif params['f_accurate_filename'] is not None:
                        # Use a user supplied json filename containing a json hash of  the resonator frequencies
                        f_accurate_filename = self.top_level_output_dir+ params['f_accurate_filename']
            else:
                        # Determine latest filename with the correct
                        # naming scheme i.e. beginning res_freq_accurate_<10-digit-unix-time>.json
                        prefix = 'res_freq_accurate'
                        found_files = glob.glob(self.top_level_output_dir+'/**/'+prefix+'*.json', recursive = True)
                        
                        if not found_files:
                           f_accurate_filename = None
                        else: 
                           # This splits the filename by _ or . and then sorts based on the 2nd last item which is the 10 digit unix string                            
                           found_files.sort(key=lambda x: re.split('_|\.',x)[-2])
                           f_accurate_filename= found_files[-1]

                        # If we have found no suitable filename, throw error and return at this point.
                        if f_accurate_filename is None:    
                           error_msg = 'No .json file with filename '+prefix+'*.json found within directory '+ self.top_level_output_dir
                           self.log.error(error_msg)
                           session.data = {"value": error_msg ,
                                   "timestamp": now}
                           message = {'block_name': 'narrow_band_sweep_string',
                              'timestamp': now,
                              'data': {'value': error_msg }}
                           return False, error_msg

            if f_accurate_list is None:
                       # We are not using a user supplied list, so
                       # try opening the file f_accurate_filename   
                       try: 
                            with open(f_accurate_filename) as f:
                               d = json.load(f)
                               f_accurate_list =  d['f_accurate_list']
                       except json.decoder.JSONDecodeError:
                            error_msg = 'Problem with decoding json file: ' + params['f_accurate_filename']
                            self.log.error(error_msg)
                            session.data = {"value": error_msg ,
                                   "timestamp": now}
                            message = {'block_name': 'narrow_band_sweep_string',
                              'timestamp': now,
                              'data': {'value': error_msg }}
                            return False, error_msg
                       except KeyError:
                            error_msg = 'Expected key f_accurate_list not found in json file: ' + params['f_accurate_filename']
                            self.log.error(error_msg)
                            session.data = {"value": error_msg ,
                                   "timestamp": now}
                            message = {'block_name': 'narrow_band_sweep_string',
                              'timestamp': now,
                              'data': {'value': error_msg }}
                            return False, error_msg
                       self.log.info('Accurate Frequencies extracted from '+f_accurate_filename)
                                     
            # At this point. f_accurate_list should defined.
            self.log.info('Found accurate frequencies of ' +str(f_accurate_list))
            
            # JL Set the all equal to supplied tone_amplitude parameter for the time being
            # This may get modified in the future.
            tone_amplitudes = [params['tone_amplitude']]*len(f_accurate_list)
            tone_phases = client.generate_newman_phases(f_accurate_list)

            self.log.info('narrow_band_sweep: Setting tone frequences, ampltiudes and phases on RFSoc.')
            client.set_tone_frequencies(f_accurate_list)
            client.set_tone_amplitudes(tone_amplitudes)
            client.set_tone_phases(tone_phases)
            self.log.info('narrow_band_sweep: Checking for input/output ADC/DAC saturation and DSP overflow on RFSoc.')
            
            try:
              outps = client.check_output_saturation()
              inps  = client.check_input_saturation()
              dspof = client.check_dsp_overflow()
    
              if outps['result']:
                raise RuntimeError(f"narrow_band_sweep: Output saturation detected: {outps['details']}")
              if inps['result']:
                raise RuntimeError(f"narrow_band_sweep: Input saturation detected: {inps['details']}")
              if dspof['result']:
                raise RuntimeError(f"narrow_band_sweep: DSP overflow detected: {dspof['details']}")

            except RuntimeError as e:
               # Send error message to feed, and log and return from function with error state.  
               runtime_error_msg = str(e)
               self.log.error(runtime_error_msg)
               session.data = {"value": runtime_error_msg ,
                                   "timestamp": now}                    
               message = {'block_name': 'status_string',
                              'timestamp': now,
                              'data': {'value':  runtime_error_msg }}
               self.agent.publish_to_feed('UKKID_feed', message)  
               self.agent.feeds['UKKID_feed'].flush_buffer()
               
               return False, runtime_error_msg

            spans = params['freq_span']*len(f_accurate_list)
            num_points = params['num_points']
            samples_per_point = params['samples_per_point']

            client.perform_sweep(f_accurate_list, spans, num_points, samples_per_point, 'up')

            while client.get_server_status()['message']['latest_sweep_data_valid'] == False:
                 self.log.info('Waiting for scan to complete, sleeping for 1 second.')
                 time.sleep(1)
                     
            self.log.info('Getting sweep data...') 
            raw_sweep = client.get_sweep_data()
            self.log.info('...done')
                     
            self.log.info('Parsing sweep data...')          
            s = client.parse_sweep_data(raw_sweep)
            self.log.info('...done')

            self.log.info('Exporting sweep data to ' + output_sweep_narrow_path +' ...')            
            client.export_sweep(output_sweep_narrow_path, s, filetype)   
            self.log.info('...done')     

            #remove slope from phase
            f = s['sweep_f']
            z = s['sweep_i']+1j*s['sweep_q']
            fcat = np.ravel(f.T)
            zcat = np.ravel(z.T)
            phicat = np.angle(zcat)
            slope = np.nanmedian(np.gradient(phicat,fcat))
            zcat *= np.exp(-1j*(slope*fcat))

            s['sweep_f'] = fcat
            s['sweep_i'] = np.real(zcat)
            s['sweep_q'] = np.imag(zcat)
            s['sweep_ei'] = np.ravel(s['sweep_ei'].T)
            s['sweep_eq'] = np.ravel(s['sweep_eq'].T)

            if params['plot_data']:
                self.log.info('Generating plots...')
                import matplotlib.pyplot as plt
                fig,(s1,s2) = plt.subplots(2,1,sharex=True)
                s1.scatter(s['sweep_f']/1e6, 20*np.log10(abs(s['sweep_i']+1j*s['sweep_q'])),marker='.',s=0.2)
                s2.scatter(s['sweep_f']/1e6, np.atan(s['sweep_q']/s['sweep_i']),marker='.',s=0.2)
                output_sweep_narrow_path = out_full_path + '/'+output_sweep_filename
                plt.savefig(output_sweep_narrow_plot_path,dpi=600)
                self.log.info('...done.')
                     
            self.log.info('narrow_band_sweep: Sweep complete.')
            # JL write something to the feed here?
            return True, 'narrow_band_sweep: Sweep complete.'

    def _abort_narrow_band_sweep(self, session, params):
          if session.status == 'running':
             session.set_status('stopping')

          if session.status != 'running':
             return False, 'Aborted narrow band sweep data.'


    
    @ocs_agent.param("f_accurate_filename", default=None, type=str)
    @ocs_agent.param("f_accurate_list", default=None, type=list)
    def set_tone_frequencies(self, session, params=None):
        """

        **Task** - 
          Task to set resonator tone frequncies. 
          If called with no supplied parameters:
             Will look for a use the mot recently created .json file whch contains tone frequencies determined either from
             a wideband or narrowband sweep.
          Alternatively supply a specific .json filename with previously fitted tone frequencies from a full band or narrow band sweep.
          Alternatively supply a list of resonator frequencies.
    

        Args
        ----
        f_accurate_filename: str, optional. Filename for file containing tone frequencies to set.
        f_accurate_list: list, optiinal. List of frequencies to set the tone frequencies to.
        """
         
        with self.lock.acquire_timeout(timeout=3.0, job='set_tone_frequencies') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("set_tone_frequencies: Preparing to set tone frequencies for: kid_stream_id: " + self.kid_stream_id)

            ########################################################                                                                                                                                                                                                                                                                                                      
            # Check to see if resonator list has been provided                                                                                                                                                                                                                                                                                                            
            # on function call, if not,                                                                                                                                                                                                                                                                                                                                   
            # see if an f_accurate_filename has been provided, and use that                                                                                                                                                                                                                                                                                               
            # else use the most recent file that has a filename of format e.g. res_freq_accurate_1761061802.json                                  
            now = time.time()
            f_accurate_list = None
            if params['f_accurate_list'] is not None:
                        # Use user-supplied python list of freqeuncies  
                        f_accurate_list = params['f_accurate_list']
            elif params['f_accurate_filename'] is not None:
                        # Use a user supplied json filename containing a list (acutally record) of frequencies
                        f_accurate_filename = self.top_level_output_dir+ params['f_accurate_filename']
            else:
                        # Determine latest filename with the correct
                        # naming scheme i.e. beginning res_freq_accurate_<ufm_name>_<10-digit-unix-time>.json
                        # For frequencies determined from a wideband sweep
                        # Or naming scheme beginning fit_summary_json_<ufm_name>_<10-digit-unix-time>.json
                        # For frequencies determined from a narrowband sweep
                        # N.B. The two types of json files have different formats, so need to be parsed differently.
                
                        prefix = 'res_freq_accurate'
                        found_files = glob.glob(self.top_level_output_dir+'/**/'+prefix+'*.json', recursive = True)
                        prefix = 'fit_summary_json'
                        found_files += glob.glob(self.top_level_output_dir+'/**/'+prefix+'*.json', recursive = True)
                        
                        if not found_files:
                           f_accurate_filename = None
                        else:
                           # This splits the filename by _ or . and then sorts based on the 2nd last item which is the 10 digit unix string                            
                           found_files.sort(key=lambda x: re.split('_|\.',x)[-2]) 
                           #found_files.sort()
                           f_accurate_filename= found_files[-1]

                        # If we have found no suitable filename, throw error and return at this point.
                        if f_accurate_filename is None:    
                           error_msg = 'No .json file with filename '+prefix+'*.json found within directory '+ self.top_level_output_dir
                           self.log.error(error_msg)
                           session.data = {"value": error_msg ,
                                   "timestamp": now}
                           message = {'block_name': 'narrow_band_sweep_string',
                              'timestamp': now,
                              'data': {'value': error_msg }}
                           return False, error_msg

            if f_accurate_list is None:
                       # We are not using a user supplied list, so
                       # try opening the file f_accurate_filename   
                       try: 
                            with open(f_accurate_filename) as f:
                               d = json.load(f)
                               if type(d) is dict: # res_freq_accurate_<ufm_name>_<10-digit-unix-time>.json type files contain a dict
                                   f_accurate_list =  d['f_accurate_list']
                               elif type(d) is list:  # fit_summary_json_<ufm_name>_<10-digit-unix-time>.json files contain a list of dicts, freqs stored in key 'f0'
                                   f_accurate_list = [x['f0'] for x in d]
                       except json.decoder.JSONDecodeError:
                            error_msg = 'Problem with decoding json file: ' + params['f_accurate_filename']
                            self.log.error(error_msg)
                            session.data = {"value": error_msg ,
                                   "timestamp": now}
                            message = {'block_name': 'narrow_band_sweep_string',
                              'timestamp': now,
                              'data': {'value': error_msg }}
                            return False, error_msg
                       except KeyError:
                            error_msg = 'Expected key f_accurate_list not found in json file: ' + params['f_accurate_filename']
                            self.log.error(error_msg)
                            session.data = {"value": error_msg ,
                                   "timestamp": now}
                            message = {'block_name': 'narrow_band_sweep_string',
                              'timestamp': now,
                              'data': {'value': error_msg }}
                            return False, error_msg
                       self.log.info('Accurate Frequencies extracted from '+f_accurate_filename)
                                     
            # At this point. f_accurate_list should defined.
            self.log.info('set_tone_frequencies: Will use tone frequencies of ' +str(f_accurate_list))
            self.log.info('set_tone_frequencies: Setting tone frequences on RFSoc.')
            client.set_tone_frequencies(f_accurate_list)
            
            self.log.info('set_tone_frequencies: complete.')
            # JL write something to the feed here?
            return True, 'set_tone_frequencies: complete.'


    def get_tone_frequencies(self, session, params=None):
        """

        **Task** - 
          Task to get resonator tone frequencies, which are written to the log and the feed. 

        Args
        ----
        None:
        """
        
        with self.lock.acquire_timeout(timeout=3.0, job='get_tone_frequencies') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("get_tone_frequencies: Preparing to get tone frequencies for: kid_stream_id: " + self.kid_stream_id)

            tone_freqs = client.get_tone_frequencies()
            self.log.info("get_tone_frequencies: Number of tones = %i " % len(tone_freqs))
            self.log.info("get_tone_frequencies: Tone frequencies " + str(tone_freqs))
            
            # JL TODO write something to the feed.            
            return True, 'get_tone_frequencies: complete.'

    @ocs_agent.param("amplitude_list", default=None, type=list)
    def set_tone_amplitudes(self, session, params=None):
        """

        **Task** - 
          Task to set resonator tone amplitudes 
  
        Args
        ----
        "amplitude_list", default=None, type=list --  List of tone amplitudes (1.0 = ADC Full Scale Deflection).   
        """
        
        with self.lock.acquire_timeout(timeout=3.0, job='set_tone_amplitudes') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("set_tone_amplitudes: Preparing to set tone ampliudes for: kid_stream_id: " + self.kid_stream_id)

            # JL Might need to add code here that checks the number of tone frequences will match
            # the length of the supplied tone amplitude array

            amp_list = params['amplitude_list']
            
            self.log.info('set_tone_amplitudes: Will use tone amplitudes of ' +str(amp_list))
            self.log.info('set_tone_amplitudes: Setting tone  amplitudes on RFSoc.')
            client.set_tone_amplitudes(amp_list)
            
            self.log.info('set_tone_amplitudes: complete.')
            # JL write something to the feed here?
            return True, 'set_tone_amplitudes complete.'

    
    def get_tone_amplitudes(self, session, params=None):
        """

        **Task** - 
          Task to get resonator tone amplitudes 
    
        Args
        ----
        None 
        """
        #################################
        # TO DO
        # 
    
        with self.lock.acquire_timeout(timeout=3.0, job='get_tone_amplitudes') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("get_tone_amplitudes: Preparing to get tone ampliudes for: kid_stream_id: " + self.kid_stream_id)

            
            # JL Might need to add code here that checks the number of tone frequences will match
            # the length of the supplied tone amplitude array

            self.log.info('get_tone_amplitudes: Getting tone  amplitudes on RFSoc.')
            amp_list = client.get_tone_amplitudes()
            self.log.info('get_tone_amplitudes: Got tone amplitudes of ' +str(amp_list))
            
            self.log.info('get_tone_amplitudes: complete.')
            # JL write something to the feed here?
            return True, 'get_tone_amplitudes complete.'    
        
    @ocs_agent.param("power_list", default=None, type=list)
    def set_tone_powers(self, session, params=None):
        """

        **Task** - 
          Task to set resonator tone powers in dBm 
    

        Args
        ----
        "power_list", default=None, type=list -- List of resonator powers in dBm 
        """
        
        with self.lock.acquire_timeout(timeout=3.0, job='set_tone_powers') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("set_tone_powers: Preparing to set tone powers for: kid_stream_id: " + self.kid_stream_id)

            pow_list = params['power_list']

            # JL Might need to add code here that checks the number of tone frequences will match                                                                                                                                                                                                                                                                         
            # the length of the supplied tone amplitude array                                                                                                                                                                                                                                                                                                             

            self.log.info('set_tone_powers: Will use tone powers of ' +str(pow_list))
            self.log.info('set_tone_powers: Setting tone  powers on RFSoc.')
            client.set_tone_powers(pow_list)
            
            self.log.info('set_tone_powers: complete.')
            # JL write something to the feed here?
            return True, 'set_tone_powers complete.'


    def get_tone_powers(self, session, params=None):
        """

        **Task** - 
          Task to get resonator tone powers 
    
        Args
        ----
        None
        """

        with self.lock.acquire_timeout(timeout=3.0, job='get_tone_powers') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False
            
            self.log.info("get_tone_powers: Preparing to get tone powers for: kid_stream_id: " + self.kid_stream_id)

            # JL Might need to add code here that checks the number of tone frequences will match                                                                                                                                                                                                                                                                         
            # the length of the supplied tone amplitude array                                                                                                                                                                                                                                                                                                             

            self.log.info('get_tone_powers: Getting tone powers on RFSoc.')
            pow_list = client.get_tone_powers()
            self.log.info('get_tone_powers: Got tone powers of ' +str(pow_list))
            
            self.log.info('get_tone_powers: complete.')
            # JL write something to the feed here?
            return True, 'get_tone_powers complete.'
        
  
       
######################################################################
# JL: We may not need command line arguments (other than kid_stream_id) when starting this agent
# But I have left the infrasructure in at the moment (a simple --mode switch)
# This should always be set to "check_state" in order to start up default "check_state" process.
######################################################################
def add_agent_args(parser_in=None):
    if parser_in is None:
        from argparse import ArgumentParser as A
        parser_in = A()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument('--mode', type=str, default='check_state',
                        choices=['check_state', 'idle'], # Command line params - either idle (does nothing) or start up the check_state process
                        help="Starting action for the Agent.")
    # Equivalent of stream_id in the SMURF world. Each option corresponds to a specific RFSoc board connected to a specific
    # sub-array of KID detectors in the focal plane.
    # Plan would be to have 7 instances per SAT of the ukkid_controller agent running
    # Each with a different kid_stream_id.
    pgroup.add_argument('--kid_stream_id', type=str, default='ufm_kid1', 
                        choices=['ufm_kid1', 'ufm_kid2','ufm_kid3','ufm_kid4', 'ufm_kid5','ufm_kid6','ufm_kid7','ufm_kid8'], # Command line params - either idle (does nothing) check_state or stream process
                        help="kid_stream_id - associated with a specific RFSoC board.")
    return parser_in


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "debug"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='UKKIDController',
                                  parser=parser,
                                  args=args)
    
    # If '--mode', 'check_state' in the command line argumetns set up in the config.yaml 
    # set startup = True and send it to the register_process below
    # this is the default behaviour. If startup is false is sent (e.g. if 'idle' is the command line parameter)
    # the default check_state process does not get started automatically, which isn't what we want.
    startup = False
    if args.mode == 'check_state':
        startup = True

    agent, runner = ocs_agent.init_site_agent(args)

    ukkid_controller = UKKIDController(agent,args)
    
    agent.register_process(
        'check_state',
        ukkid_controller.check_state,
        ukkid_controller._stop_check_state,
        startup=startup)

    agent.register_task('det_res_freq_from_sweep_data',ukkid_controller.det_res_freq_from_sweep_data)
    agent.register_task('initialise_server', ukkid_controller.initialise_server)
    agent.register_task('get_system_information', ukkid_controller.get_system_information)
    agent.register_task('stream', ukkid_controller.stream, aborter=ukkid_controller._abort_stream)
    agent.register_task('full_band_sweep', ukkid_controller.full_band_sweep, aborter=ukkid_controller._abort_full_band_sweep)
    agent.register_task('narrow_band_sweep', ukkid_controller.narrow_band_sweep, aborter=ukkid_controller._abort_narrow_band_sweep)
    agent.register_task('fit_from_narrow_sweep',ukkid_controller.fit_from_narrow_sweep)
    agent.register_task('set_tone_frequencies',ukkid_controller.set_tone_frequencies)
    agent.register_task('get_tone_frequencies',ukkid_controller.get_tone_frequencies)
    agent.register_task('set_tone_amplitudes',ukkid_controller.set_tone_amplitudes)
    agent.register_task('get_tone_amplitudes',ukkid_controller.get_tone_amplitudes)
    agent.register_task('set_tone_powers',ukkid_controller.set_tone_powers)
    agent.register_task('get_tone_powers',ukkid_controller.get_tone_powers)
    
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
