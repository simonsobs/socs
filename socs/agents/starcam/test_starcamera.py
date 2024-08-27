import os
import socket
import struct

logodds = 1e8
latitude = 39.9502777778
longitude = -75.1877777778
height = 9.144
exposure = 700
timelimit = 1
set_focus_to_amount = 0
auto_focus_bool = 1
start_focus = 0
end_focus = 0
step_size = 5
photos_per_focus = 3
infinity_focus_bool = 0
set_aperture_steps = 0
max_aperture_bool = 0
make_HP_bool = 0
use_HP_bool = 0
spike_limit_value = 3
dynamic_hot_pixels_bool = 1
r_smooth_value = 2
high_pass_filter_bool = 0
r_high_pass_filter_value = 10
centroid_search_border_value = 1
filter_return_image_bool = 0
n_sigma_value = 2
star_spacing_value = 15

cmds_for_camera = struct.pack('ddddddfiiiiiiiiiifffffffff', logodds, latitude, longitude, height, exposure,
                              timelimit, set_focus_to_amount, auto_focus_bool, start_focus, end_focus,
                              step_size, photos_per_focus, infinity_focus_bool, set_aperture_steps,
                              max_aperture_bool, make_HP_bool, use_HP_bool, spike_limit_value,
                              dynamic_hot_pixels_bool, r_smooth_value, high_pass_filter_bool,
                              r_high_pass_filter_value, centroid_search_border_value, filter_return_image_bool,
                              n_sigma_value, star_spacing_value)


def establishStarCamSocket(StarCam_IP, user_port):
    server_addr = (StarCam_IP, user_port)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(server_addr)
    print("Connected to %s" % repr(server_addr))
    return (s, StarCam_IP, user_port)


def sendCommands(data_to_send, s, StarCam_IP, StarCam_PORT):
    s.sendto(data_to_send, (StarCam_IP, StarCam_PORT))
    print("Commands sent to camera. Will display confirmation")
    return 1


def getStarCamData(client_socket):
    # number of expected bytes is hard-coded
    try:
        (StarCam_data, _) = client_socket.recvfrom(224)
        backupStarCamData(StarCam_data)
        print("Received Star Camera data.")
        return StarCam_data
    except ConnectionResetError:
        return None
    except struct.error:
        return None


def backupStarCamData(StarCam_data):
    script_dir = os.path.dirname(os.path.realpath(__file__))
    # write this data to a .txt file (always updating)
    data_file = open(script_dir + os.path.sep + "data.txt", "a+")
    unpacked_data = struct.unpack_from("dddddddddddddiiiiiiiiddiiiiiiiiiiiiiifiii", StarCam_data)
    text = ["%s," % str(unpacked_data[1]), "%s," % str(unpacked_data[1]),
            "%s," % str(unpacked_data[6]), "%s," % str(unpacked_data[7]), "%s," % str(unpacked_data[8]),
            "%s," % str(unpacked_data[9]), "%s," % str(unpacked_data[10]), "%s," % str(unpacked_data[11]),
            "%s\n" % str(unpacked_data[12])]
    print(text)
    data_file.writelines(text)
    data_file.close()


s, ip, user_port = establishStarCamSocket("10.10.10.167", 8000)
command_success = sendCommands(cmds_for_camera, s, ip, user_port)

if command_success == 1:
    while True:
        starcamdata = getStarCamData(s)
    try:
        backupStarCamData(starcamdata)
    except TypeError:
        pass
