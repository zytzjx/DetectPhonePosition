import os
import io
import cv2
import time
import redis
import logging
import requests
import threading
import gphoto2 as gp
import subprocess
from datetime import datetime
from detectphoneUI import Ui_Frame
from PyQt5.QtGui import QPixmap
from PIL.ImageQt import ImageQt
from PIL import Image, ImageDraw
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer


class PreparationThread(QThread):
    done = pyqtSignal(str)
    progess = pyqtSignal(str)

    def __inti__(self):
        super(PreparationThread, self).__init__()

    def run(self):
        ok = True
        # start powermanager
        self.progess.emit("Prepare Hardware...")
        time.sleep(1)
        self.progess.emit("Invoke PowerManagement...")
        ahome = os.getenv('ATHENAHOME', '/opt/futuredial/athena')
        fn = os.path.join(ahome, 'powermanager')
        if os.path.exists(fn):
            p = subprocess.Popen([fn], cwd=ahome)       
        time.sleep(3)
        self.progess.emit("Turn LEDs...")
        # power off camera
        try:
            requests.get('http://127.0.0.1:8010/12', params={'on': 0}) 
            requests.get('http://127.0.0.1:8010/9', params={'on': 0}) 
            requests.get('http://127.0.0.1:8010/10', params={'on': 0}) 
            requests.get('http://127.0.0.1:8010/11', params={'on': 0}) 
        except:
            ok = False
            print("exception.")
        # 3. LED 5 and 8 on
        try:
            requests.get('http://127.0.0.1:8010/4', params={'on': 1}) 
            requests.get('http://127.0.0.1:8010/5', params={'on': 1}) 
        except:
            ok = False
            print("exception.")
        time.sleep(1)
        self.progess.emit("Starting Camera...")
        try:
            requests.get('http://127.0.0.1:8010/9', params={'on': 1}) 
            requests.get('http://127.0.0.1:8010/10', params={'on': 1}) 
            requests.get('http://127.0.0.1:8010/11', params={'on': 1}) 
            time.sleep(1)
            requests.get('http://127.0.0.1:8010/12', params={'on': 1}) 
        except:
            ok = False
            print("exception.")
        time.sleep(7)   
        self.done.emit('completed' if ok else 'failed')

class CameraWorker(QThread):
    def __init__(self):
        super(CameraWorker, self).__init__()
        self.quitEvent = threading.Event()
        self.cb = None        
        self.ev = None
        self.evs = []
        self.mode = 1
        self.filename = None
        self.new_ev = None

    def start_preview(self, cb=None):
        # mode = 1, preview mode
        self.mode = 1
        self.cb = cb
        self.start()
       
    def stop_preview(self):
        # mode = 1, preview mode
        self.quitEvent.set()

    def start_takephoto(self, filename, ev):
        self.mode = 0
        self.ev = ev
        self.filename = filename
        self.start()

    def set_ev(self, ev):
        if ev != self.ev:
            self.new_ev = ev

    def camera_find_by_serialnumber(self, serialnumber):
        logging.info('camera_find_by_serialnumber: ++ sn = {}'.format(serialnumber))
        found = False
        ret = None
        try:
            cnt, cameras = gp.gp_camera_autodetect()        
            for i in range(cnt):
                if len(cameras[i]) == 2 :
                    addr = cameras[i][1]
                    port_info_list = gp.PortInfoList()
                    port_info_list.load()
                    idx = port_info_list.lookup_path(addr)
                    c = gp.Camera()
                    c.set_port_info(port_info_list[idx])
                    c.init()
                    config = c.get_config()
                    OK, sn = gp.gp_widget_get_child_by_name(config, 'serialnumber')
                    if OK >= gp.GP_OK:
                        sn_text = sn.get_value()
                        if serialnumber == sn_text[-len(serialnumber):] :
                            found =True
                            ret = c
                    if not found:
                        c.exit()
                if found:
                    break
        except:
            pass
        logging.info('camera_find_by_serialnumber: -- ret={}'.format(ret))
        return ret

    def get_ev(self, camera):
        if bool(camera):
            err, ep = gp.gp_camera_get_single_config(camera, 'exposurecompensation')
            if err >= gp.GP_OK:
                v = ep.get_value()
                self.ev=v
                for i in ep.get_choices():
                    v = float(i)
                    v = v*10
                    if v % 10 != 5:
                        self.evs.append(i)
                self.evs.sort()

    def run(self):
        # import debugpy
        # debugpy.debug_this_thread()
        if self.mode == 1:
            self.run_preview()
        elif self.mode == 0:
            self.run_takephoto()
        else:
            pass
    
    def run_takephoto(self):
        logging.info('run_takephoto: ++')
        rc = redis.Redis()
        x = rc.get('camera.TP')
        if bool(x):
            x = x.decode('utf-8')
            camera = self.camera_find_by_serialnumber(x)
            if camera is not None:
                try:
                    # err, ep = gp.gp_camera_get_single_config(camera, 'exposurecompensation')
                    # if err >= gp.GP_OK:
                    #     v = ep.get_value()
                    #     ep.set_value(self.ev)
                    #     err = gp.gp_camera_set_single_config(camera, 'exposurecompensation', ep)
                    #     if err >= gp.GP_OK:
                    #         pass
                    file_path = camera.capture(gp.GP_CAPTURE_IMAGE)
                    camera_file = camera.file_get(file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL)
                    camera_file.save(self.filename)
                except:
                    pass
                camera.exit()
        rc.close()
        logging.info('run_takephoto: --')

    def run_preview(self):
        logging.info('run_preview: ++')
        rc = redis.Redis()
        while not self.quitEvent.is_set():
            x = rc.get('camera.TP')
            if bool(x):
                x = x.decode('utf-8')
                camera = self.camera_find_by_serialnumber(x)
                if camera is not None:
                    # self.get_ev(camera)
                    # frame=0
                    while not self.quitEvent.is_set():
                        try:
                            # if bool(self.new_ev):
                            #     err, ep = gp.gp_camera_get_single_config(camera, 'exposurecompensation')
                            #     if err >= gp.GP_OK:
                            #         v = ep.get_value()
                            #         ep.set_value(self.new_ev)
                            #         err = gp.gp_camera_set_single_config(camera, 'exposurecompensation', ep)
                            #         if err >= gp.GP_OK:
                            #             self.ev = self.new_ev
                            #             self.new_ev = None
                            camera_file = camera.capture_preview() 
                            # frame += 1
                            # logging.info('frame: {}'.format(frame))
                            err, buf = gp.gp_file_get_data_and_size(camera_file)
                            if err >= gp.GP_OK:
                                image = Image.open(io.BytesIO(buf))
                                image = image.rotate(180)
                                if self.cb is not None:
                                    self.cb(image)
                        except:
                            pass
                    camera.exit()
                else:
                    time.sleep(3)
        rc.close()
        logging.info('run_preview: --')
        pass

class DetectPhoneWidget(QtWidgets.QWidget, Ui_Frame):
    def __init__(self, parent=None):
        super(DetectPhoneWidget, self).__init__(parent)
        self.setupUi(self)
        self.pushButtonExit.clicked.connect(self.exit_cliecked)
        self.setWindowIcon(QtGui.QIcon(os.path.join(athena_home,'Athena.ico')))
        self.l = logging.getLogger('DetectPhoneTool')
        self.hardware_ready = False
        self.current_frame = None
        self.current_frame_lock=threading.Lock()
        self.pushButtonTest.clicked.connect(self.testthread)

    def testthread(self):
        self.current_frame_lock.acquire()
        if self.current_frame:
            now = datetime.now() # current date and time
            self.current_frame.save(now.strftime("%Y%m%d-%H%M%S")+".jpg")
        self.current_frame_lock.release()

    def exit_cliecked(self):
        self.close()
        pass


    def closeEvent(self, event):
        logging.info('closeEvent: ++')
        
        self.stop_camera()
        try:
            requests.get('http://localhost:8010/lift/go', params={'p': 0})
            requests.get('http://127.0.0.1:8010/4', params={'on': 0}) 
            requests.get('http://127.0.0.1:8010/5', params={'on': 0}) 
            requests.post('http://localhost:8010/exitsystem', json={"name":"xyz","password":"xyz"})
        except:
            pass
        logging.info('closeEvent: --')

    def start_camera(self):
        self.thread = CameraWorker()
        self.thread.start_preview(self.on_frame_arrival)
    
    def stop_camera(self):
        if self.thread is not None:
            try:
                self.thread.stop_preview()
                self.thread.join()
            except:
                pass

    def on_frame_arrival(self, frame):
        image = frame.copy()
        self.current_frame_lock.acquire()
        self.current_frame = image
        self.current_frame_lock.release()
        imageQ = ImageQt(image)
        pixmap = QPixmap.fromImage(imageQ)
        self.labelImage.setPixmap(pixmap) 
 
    def start_powermanager(self):
        # ahome = os.environ['ATHENAHOME']
        ahome = os.getenv('ATHENAHOME', '/opt/futuredial/athena')
        fn = os.path.join(ahome, 'powermanager')
        if os.path.exists(fn):
            subprocess.Popen([fn], cwd=ahome)            
        pass

    def prepare_hardware_complete(self, msg):
        self.timer.stop()
        self.dlg.close()
        self.dlg=None
        if msg == 'completed':
            self.hardware_ready = True
            self.start_camera()
        if msg == 'failed':
            msgBox = QtWidgets.QMessageBox()
            msgBox.setIcon(QtWidgets.QMessageBox.Critical)        
            msgBox.setWindowTitle("Initial Hardware Failed")
            msgBox.setText(f'Hardware fail to initialize. Please close application and try again.')
            msgBox.setStandardButtons(QtWidgets.QMessageBox.Ok)
            msgBox.exec()
            
    def showEvent(self, event):
        self.l.info('Windows shown.')
        x = os.getenv('ATHENAHARDWARE', 'True')
        if x.lower() == 'false':
            self.hardware_ready = True
        else:
            if not self.hardware_ready:
                self.prepare_hardware()

    def prepare_hardware(self):
        self.l.info('prepare_hardware: ++')
        self.dlg = QtWidgets.QProgressDialog(self)
        self.dlg.setWindowTitle("Please waiting") 
        self.dlg.setLabelText("Initializing")
        self.dlg.setCancelButtonText("cancel")
        self.dlg.setWindowModality(Qt.WindowModal)
        self.dlg.forceShow()
        self.dlg.setRange(0, 10)
        self.dlg.setValue(0) 
        self.dlg.setAutoClose(False)
        self.dlg.setAutoReset(False)
        self.t = PreparationThread()
        self.t.done.connect(self.prepare_hardware_complete)
        self.t.progess.connect(self.test_progress)
        self.t.start()
        self.timer = QTimer()
        self.timer.timeout.connect(self.test_progress_1)
        self.timer.start(1000)
        self.l.info('prepare_hardware: --')

    def test_progress(self, msg):
        self.dlg.setLabelText(msg)
        
    def test_progress_1(self):
        if self.dlg is not None:
            v = self.dlg.value()
            m = self.dlg.maximum()
            print(v,m)
            if v+1<=m and v>=0:
                self.dlg.setValue(v+1)


if __name__ == "__main__":
    import sys
    logging.basicConfig(format='%(asctime)s: %(levelname)s: %(name)s: %(message)s', level=logging.INFO)
    global athena_home
    athena_home = os.getenv("ATHENAHOME", '')
    if not bool(athena_home):
        athena_home = '/opt/futuredial/athena'
    app = QtWidgets.QApplication(sys.argv)
    w = DetectPhoneWidget()
    w.show()
    sys.exit(app.exec_())
