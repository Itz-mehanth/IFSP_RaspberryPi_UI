import threading
import queue
import time
import platform
from datetime import datetime
from tkinter import *
import subprocess
from tkinter.ttk import Style
from decimal import Decimal, getcontext
import geocoder  # Import geocoder library for location
import cv2
from PIL import Image, ImageTk
import os
from tkintermapview import TkinterMapView
import firebase_admin
from firebase_admin import credentials, firestore
import serial
import time
import string
import pynmea2


def getLoc():
    try:
        # Open the serial port with the specified baud rate and timeout
        ser = serial.Serial("/dev/ttyS0", baudrate=9600, timeout=1)
        dataout = pynmea2.NMEAStreamReader()

        while True:
            newdata = ser.readline()
            if newdata:
                try:
                    # Decode and parse the NMEA sentence
                    decoded_data = newdata.decode('utf-8')
                    if '$GPRMC' in decoded_data:
                        print(f"Raw data: {decoded_data}")
                        newmsg = pynmea2.parse(decoded_data)
                        lat = newmsg.latitude
                        lng = newmsg.longitude

                        if lat and lng:
                            gps = f"Latitude={lat} and Longitude={lng}"
                            print(gps)
                            return [lat, lng]
                        else:
                            print("Invalid latitude or longitude.")
                except pynmea2.ParseError as e:
                    print(f"ParseError: {e}")
                except Exception as e:
                    print(f"Exception during parsing: {e}")
            else:
                print("No data received.")
    except serial.SerialException as e:
        print(f"SerialException: {e}")
    except Exception as e:
        print(f"Exception: {e}")

    # If the loop exits without returning valid coordinates
    return [None, None]


# Initialize Firebase
cred = credentials.Certificate('assets/serviceAccountKey.json')
firebase_admin.initialize_app(cred)

# Initialize Firestore
db = firestore.client()

getcontext().prec = 50

# Global variables for selected state
gallery_selected = True
camera_selected = False
map_selected = False
cache = {}
data_queue = queue.Queue()  # Queue for safely passing data between threads


# Function to fetch data in a background thread
def fetch_plant_data():
    plant_collection = db.collection('plant_details')
    docs = plant_collection.stream()

    markers = []  # List to store marker information
    i = 0
    for doc in docs:
        data = doc.to_dict()
        plant_ref = db.collection('plant_details').document(doc.id)
        coordinates_ref = plant_ref.collection('coordinates')
        plantCoords = coordinates_ref.stream()

        common_name = data.get('Common Name')
        print(f"{i}. Getting location and common name for {common_name}")

        coordinates = []
        for plantCoord in plantCoords:
            location = plantCoord.to_dict().get('location')
            print(f"{i}. Lat:{location.latitude} Lon:{location.longitude}")
            if location:
                coordinates.append((location.latitude, location.longitude))
                print(f"GeoPoint: Latitude = {location.latitude}, Longitude = {location.longitude}")

        if coordinates and common_name:
            print("Got location and common name")
            markers.append({"name": common_name, "coordinates": coordinates})
        i += 1

    data_queue.put(markers)  # Pass the data to the main thread via the queue
    print("Data fetched and added to queue.")


# Function to fetch and cache data in a separate thread
def initialize_cache():
    def fetch_and_cache():
        fetch_plant_data()

    thread = threading.Thread(target=fetch_and_cache)
    thread.start()


# Function to periodically check the queue and update the UI
def check_queue():
    try:
        markers = data_queue.get_nowait()
        cache["markers"] = markers
        print("Data retrieved from queue and cached.")
        if map_selected:
            show_map()
    except queue.Empty:
        pass

    root.after(100, check_queue)  # Check the queue every 100ms


# Example: Start periodic cache refresh every hour
initialize_cache()


def get_current_location():
    g = geocoder.ip('me')
    return g.latlng  # Returns a list [latitude, longitude]


def show_map():
    for widget in main_frame.winfo_children():
        widget.destroy()

    markers = cache.get("markers", None)  # Use cached data if available
    current_location = get_current_location()

    map_widget = TkinterMapView(main_frame, width=800, height=600, corner_radius=0)
    map_widget.pack(fill="both", expand=True)
    if current_location:
        lat, lon = current_location
        map_widget.set_position(lat, lon)
        map_widget.set_zoom(10)
        map_widget.set_marker(lat, lon, text="You")

    if markers:
        for marker in markers:
            for coord in marker["coordinates"]:
                latitude = Decimal(coord[0])
                longitude = Decimal(coord[1])
                map_widget.set_marker(latitude, longitude, text=marker["name"])
    else:
        map_widget.set_position(0, 0)
        map_widget.set_zoom(1)


# Function to create resized icon images for Tkinter buttons
def createIcon(path, selected, size=(32, 32)):
    if selected:
        path += "_selected.png"
    else:
        path += ".png"

    icon = Image.open(path).convert("RGBA")
    icon = icon.resize(size)
    tk_icon = ImageTk.PhotoImage(icon)
    return tk_icon


def show_gallery():
    images_dir = os.getcwd()
    image_files = [f for f in os.listdir(images_dir) if f.startswith('captured_image_') and f.endswith('.png')]

    gallery_frame = Frame(main_frame)
    gallery_frame.pack(fill='both', expand=True)

    row = 0
    col = 0
    max_cols = 3  # Number of columns in the grid
    thumbnail_size = (150, 150)  # Size of thumbnail images

    for image_file in image_files:
        image_path = os.path.join(images_dir, image_file)
        image = Image.open(image_path)
        image.thumbnail(thumbnail_size)
        tk_image = ImageTk.PhotoImage(image)

        image_label = Label(gallery_frame, image=tk_image)
        image_label.image = tk_image  # Keep a reference to avoid garbage collection
        image_label.grid(row=row, column=col, padx=5, pady=5)

        col += 1
        if col >= max_cols:
            col = 0
            row += 1


# Function to handle page navigation and update the main frame content
def navigate(page):
    global gallery_selected, camera_selected, map_selected

    gallery_selected = camera_selected = map_selected = False

    for widget in main_frame.winfo_children():
        widget.destroy()

    if page == 'gallery':
        gallery_selected = True
    elif page == 'camera':
        camera_selected = True
    elif page == 'map':
        map_selected = True

    gallery_icon = createIcon("assets/gallery", gallery_selected)
    camera_icon = createIcon("assets/camera", camera_selected)
    marker_icon = createIcon("assets/marker", map_selected)

    home_button.config(image=gallery_icon)
    settings_button.config(image=camera_icon)
    info_button.config(image=marker_icon)

    home_button.image = gallery_icon
    settings_button.image = camera_icon
    info_button.image = marker_icon

    if page == 'gallery':
        show_gallery()
    elif page == 'camera':
        show_camera()
    elif page == 'map':
        show_map()


def show_camera():
    # Detect the operating system
    system = platform.system()

    # Initialize camera capture based on OS
    if system == 'Windows':
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    elif system == 'Linux':  # This includes Raspberry Pi
        cap = cv2.VideoCapture(0)
    else:
        print(f"Unsupported OS: {system}")
        return

    def update_frame():
        # Read frame from the camera
        ret, frame = cap.read()
        if ret:
            cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(cv2image)
            imgtk = ImageTk.PhotoImage(image=img)
            camera_label.imgtk = imgtk
            camera_label.config(image=imgtk)
        camera_label.after(10, update_frame)  # Refresh frame every 10ms

    def capture_image():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        geopoint = getLoc()

        while geopoint == [None, None]:
            print("Waiting for GPS location...")
            time.sleep(1)
            geopoint = getLoc()

        if geopoint:
            latitude = geopoint[0]
            longitude = geopoint[1]
            image_filename = f'captured_frame_{timestamp}/{latitude}/{longitude}.png'

            if system == 'Linux':
                # Run ffmpeg to capture a frame from the camera on Linux/Raspberry Pi
                command = [
                    'ffmpeg',
                    '-f', 'video4linux2',
                    '-i', '/dev/video0',
                    '-vf', 'scale=320:340',
                    '-vframes', '1',
                    image_filename
                ]
            elif system == 'Windows':
                # Windows specific command to capture a frame using ffmpeg or OpenCV methods
                # Example (this is more complex and might need adjustments):
                command = [
                    'ffmpeg',
                    '-f', 'dshow',
                    '-i', 'video="Your Camera Name"',
                    '-vf', 'scale=320:340',
                    '-vframes', '1',
                    image_filename
                ]
            else:
                print("Error: Unsupported OS for image capture.")
                return

            try:
                subprocess.run(command, check=True)
                print(f"Image captured and saved as {image_filename}")

                if os.path.exists(image_filename):
                    image = Image.open(image_filename)
                    tk_image = ImageTk.PhotoImage(image)
                    camera_label.config(image=tk_image)
                    camera_label.image = tk_image
                else:
                    print("Error: Captured image not found.")
            except subprocess.CalledProcessError as e:
                print(f"Error capturing image: {e}")

    overlay_frame = Frame(main_frame)
    overlay_frame.pack(fill='both', expand=True)

    camera_label = Label(overlay_frame)
    camera_label.pack(fill='both', expand=True)

    capture_button = Button(overlay_frame, text="Capture Image", command=capture_image)
    capture_button.place(relx=0.5, rely=0.9, anchor='center', width=150, height=50)

    update_frame()


# Create main window
root = Tk()
root.title("Medplant")
root.geometry("600x400")

# Create the main container frames
side_frame = Frame(root, width=100, relief='ridge', background='white')
side_frame.config()
side_frame.pack(side='left', fill='y')
main_frame = Frame(root, relief='sunken')
main_frame.pack(side='right', expand=True, fill='both')

gallery_icon = createIcon("assets/gallery", gallery_selected)
camera_icon = createIcon("assets/camera", camera_selected)
marker_icon = createIcon("assets/marker", map_selected)

style = Style()
style.configure('IconStyle', relief='flat', padding=10, borderwidth=0)

home_button = Button(side_frame, image=gallery_icon, highlightthickness=0,
                     command=lambda: navigate('gallery'), relief='flat',
                     background='white', activebackground='white')
home_button.pack(fill='x', expand=True, padx=10, pady=20)

settings_button = Button(side_frame, image=camera_icon, highlightthickness=0,
                         command=lambda: navigate('camera'), relief='flat',
                         background='white', activebackground='white')
settings_button.pack(fill='x', expand=True, padx=10, pady=20)

info_button = Button(side_frame, image=marker_icon, highlightthickness=0,
                     command=lambda: navigate('map'), relief='flat',
                     background='white', activebackground='white')
info_button.pack(fill='x', expand=True, padx=10, pady=20)

navigate('gallery')

# Start the data fetch process in the background
initialize_cache()

# Start checking the queue for updates
root.after(100, check_queue)

root.mainloop()
