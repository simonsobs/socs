import os


def assert_session_success(session, success=True):
    print("\n{} messages:".format(session['op_name']))
    for m in session['messages']:
        print('>>> {}'.format(m))
    assert session['success'] == success


def test_set_values(client):
    # Sets channel 1 to be configured for a diode
    diode_params = {
        'sensor': 1,
        'auto_range': 1,
        'enabled': 1,
    }

    client.set_values.start(channel=1, **diode_params)
    ok, msg, session = client.set_values.wait()
    assert_session_success(session)


def test_upload_cal_curve(client):

    cal_file = os.path.join(os.getcwd(), 'dt-670_standard_curve.txt')
    client.upload_cal_curve.start(channel=1, filename=cal_file)
    ok, msg, session = client.upload_cal_curve.wait()
    assert_session_success(session)


def test_operation_locking(client):

    client.acq.start()

    client.set_values.start(channel=1)
    ok, msg, session = client.set_values.wait()
    assert_session_success(session, success=False)

    client.acq.stop()
    client.acq.wait()

    client.set_values.start(channel=1)
    ok, msg, session = client.set_values.wait()
    assert_session_success(session)
