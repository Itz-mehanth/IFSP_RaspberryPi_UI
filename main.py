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

from google.cloud.storage import bucket
from tkintermapview import TkinterMapView
import firebase_admin
from firebase_admin import credentials, firestore
import serial
import time
import string
import pynmea2


def getLoc():
    try:
        # Determine the serial port based on the operating system
        if platform.system() == "Windows":
            port = "COM3"  # Update this to your actual COM port on Windows
        else:  # Assuming it's a Raspberry Pi or Linux-based system
            port = "/dev/ttyS0"  # Update this if your GPS module is on a different port

        # Open the serial port with the specified baud rate and timeout
        ser = serial.Serial(port, baudrate=9600, timeout=1)
        dataout = pynmea2.NMEAStreamReader()

        while True:
            newdata = ser.readline()
            if newdata:
                try:
                    decoded_data = newdata.decode('utf-8', errors='ignore').strip()

                    if decoded_data.startswith('$'):
                        print(f"Raw data: {decoded_data}")

                        if '$GPRMC' in decoded_data:
                            newmsg = pynmea2.parse(decoded_data)
                            lat = newmsg.latitude
                            lng = newmsg.longitude

                            if lat and lng:
                                gps = f"Latitude={lat} and Longitude={lng}"
                                print(gps)
                                return [lat, lng]
                            else:
                                print("Invalid latitude or longitude.")
                    else:
                        print(f"Ignored non-NMEA data: {decoded_data}")

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


capslock = False
current_text_field = None


def open_in_app_keyboard(img_path):
    global main_frame, current_text_field

    # Clear the main frame
    for widget in main_frame.winfo_children():
        widget.destroy()

    # Create the keyboard window frame
    keyboard_window = Frame(main_frame)
    keyboard_window.pack()

    keyboard_window.grid_rowconfigure(1, weight=1)  # Row for the image and text fields
    keyboard_window.grid_rowconfigure(2, weight=1)  # Row for the keyboard
    keyboard_window.grid_columnconfigure(0, weight=1)  # Column for the image
    keyboard_window.grid_columnconfigure(1, weight=1)  # Column for the text fields

    # Display the image
    image = Image.open(img_path)
    image.thumbnail((200, 200))  # Adjust size as needed
    tk_image = ImageTk.PhotoImage(image)

    image_label = Label(keyboard_window, image=tk_image)
    image_label.image = tk_image  # Keep a reference to avoid garbage collection
    image_label.grid(row=1, column=0, padx=3, pady=8, sticky="nsew")

    # Frame for text fields
    text_frame = Frame(keyboard_window)
    text_frame.grid(row=1, column=1, padx=3, pady=10, sticky="nsew")

    # Single-line Entry for the Image Name
    name_label = Label(text_frame, text="Image Name:")
    name_label.pack()

    name_entry = Entry(text_frame, width=35)
    name_entry.pack(pady=2)

    # Single-line Entry for the Scientific Name
    scientific_name_label = Label(text_frame, text="Scientific Name:")
    scientific_name_label.pack()

    scientific_name_entry = Entry(text_frame, width=35)
    scientific_name_entry.pack(pady=2)

    # Single-line Entry for the Family
    family_label = Label(text_frame, text="Family:")
    family_label.pack()

    family_entry = Entry(text_frame, width=35)
    family_entry.pack(pady=2)


    # Scrollable Text Widget for the Short Description
    desc_label = Label(text_frame, text="Short Description:")
    desc_label.pack()

    desc_text_frame = Frame(text_frame)
    desc_text_frame.pack(fill="both", expand=True)

    desc_scrollbar = Scrollbar(desc_text_frame)
    desc_scrollbar.pack(side=RIGHT, fill=Y)

    desc_entry = Text(desc_text_frame, wrap="word", height=4, width=20, yscrollcommand=desc_scrollbar.set)
    desc_entry.pack(side=LEFT, fill="both", expand=True)

    desc_scrollbar.config(command=desc_entry.yview)

    # Keyboard Frame
    keyboard_frame = Frame(keyboard_window, background="lightgrey")
    keyboard_frame.grid(row=2, column=0, columnspan=2, padx=1, pady=10, sticky="nsew")

    # Function to insert text into the current active text field
    def insert_text(char):
        global capslock, current_text_field

        if current_text_field is None:
            return

        if isinstance(current_text_field, Text):
            if char == "Backspace":
                current_text = current_text_field.get("1.0", "end-1c")
                if current_text:
                    current_text_field.delete(f"{current_text_field.index(INSERT)}-1c", INSERT)
            elif char == " ":
                current_text_field.insert(INSERT, ' ')
            elif char == "Capslock":
                capslock = not capslock
                # Update UI or button text if needed
            else:
                if capslock and char.isalpha():
                    char = char.upper()
                current_text_field.insert(INSERT, char)
        elif isinstance(current_text_field, Entry):
            current_text = current_text_field.get()
            if char == "Backspace":
                if current_text:
                    current_text_field.delete(len(current_text) - 1, END)
            elif char == " ":
                current_text_field.insert(END, ' ')
            elif char == "Capslock":
                capslock = not capslock
                # Update UI or button text if needed
            else:
                if capslock and char.isalpha():
                    char = char.upper()
                current_text_field.insert(END, char)

    # Create a simple keyboard layout
    keys = [
        ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', 'Backspace'],
        ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', ':', '[', ']'],
        ['Capslock', 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', '"', '\''],
        ['z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.'],
        [' ']
    ]

    key_width = 3
    key_height = 1

    # Add keyboard buttons for both text entries
    for row in keys:
        key_row = Frame(keyboard_frame)
        key_row.pack()
        for key in row:
            if key == "Capslock":
                button = Button(key_row, text=key, relief="groove", width=10, height=key_height,
                                command=lambda: insert_text("Capslock"))
            elif key == "Backspace":
                button = Button(key_row, text=key, relief="groove", width=10, height=key_height,
                                command=lambda: insert_text("Backspace"))
            elif key == " ":
                button = Button(key_row, text=key, relief="groove", width=20, height=key_height,
                                command=lambda: insert_text(" "))
            else:
                button = Button(key_row, text=key, relief="groove", width=key_width, height=key_height,
                                command=lambda k=key: insert_text(k))
            button.pack(side=LEFT, padx=2, pady=2)

    # Set the current text field to name_entry initially
    current_text_field = name_entry

    # Update current_text_field when the user clicks on text fields
    name_entry.bind("<Button-1>", lambda e: set_current_text_field(name_entry))
    desc_entry.bind("<Button-1>", lambda e: set_current_text_field(desc_entry))
    scientific_name_entry.bind("<Button-1>", lambda e: set_current_text_field(scientific_name_entry))
    family_entry.bind("<Button-1>", lambda e: set_current_text_field(family_entry))

    # Function to set the current text field
    def set_current_text_field(text_field):
        global current_text_field
        current_text_field = text_field

    # Submit button
    submit_button = Button(keyboard_window, text="Upload", background="blue", foreground="white",
                           command=lambda: upload_to_firebase(
                               img_path,
                               name_entry.get().strip(),
                               desc_entry.get("1.0", "end-1c").strip(),
                               latitude=383393.0,
                               longitude=535353.0,
                               family=family_entry.get().strip(),
                               scientific_name=scientific_name_entry.get().strip()
                           ))
    submit_button.grid(row=3, column=0, columnspan=2, pady=2)


def uploadToStorage(selected_image):
    open_in_app_keyboard(selected_image)


def upload_to_firebase(image_path, name, description, latitude, longitude, family, scientific_name):
    print("Uploading")

    # Upload image to Firebase Storage
    image_file_name = os.path.basename(image_path)
    folder_name = name  # Folder name in Storage
    blob = bucket.blob(f'images/{folder_name}/{image_file_name}')
    blob.upload_from_filename(image_path)

    # Get the URL of the uploaded image
    image_url = blob.public_url

    # Prepare data for Firestore
    plant_details = {
        'Common Name': name,
        'Description': description,
        'Family': family,
        'Scientific Name': scientific_name
    }

    coordinates = {
        'location': firestore.GeoPoint(latitude, longitude)
    }

    # Upload plant details to Firestore
    plant_ref = db.collection('plant_details').document(name)
    plant_ref.set(plant_details)

    # Upload image URL to Firestore
    images_ref = plant_ref.collection('images').document(image_file_name)
    images_ref.set({
        'image_url': image_url
    })

    # Upload coordinates to Firestore
    coordinates_ref = plant_ref.collection('coordinates').document('location')
    coordinates_ref.set(coordinates)

    print("Upload complete")


def show_gallery():
    if platform.system() == "Windows":
        images_dir = 'C:/raspberry_images'  # Update this path as needed
    else:  # Assuming it's a Raspberry Pi or Linux-based system
        images_dir = '/home/mehant/Pictures'  # Update this path as needed

    # Verify directory existence
    if not os.path.exists(images_dir):
        print(f"Error: Directory {images_dir} does not exist.")
        return

    # List all files in the directory
    image_files = [f for f in os.listdir(images_dir) if f.startswith('captured_frame_') and f.endswith('.png')]

    # Debugging: Print found image files
    print(f"Image files found: {image_files}")

    # Create a scrollable gallery
    gallery_container = Frame(main_frame)
    gallery_container.pack(fill='both', expand=True)

    canvas = Canvas(gallery_container)
    canvas.pack(side=LEFT, fill='both', expand=True)

    scrollbar = Scrollbar(gallery_container, orient=VERTICAL, command=canvas.yview)
    scrollbar.pack(side=RIGHT, fill=Y)

    gallery_frame = Frame(canvas)
    canvas.create_window((0, 0), window=gallery_frame, anchor='nw')
    canvas.config(yscrollcommand=scrollbar.set)

    # Configure the scroll region
    def configure_scroll_region(event):
        canvas.config(scrollregion=canvas.bbox("all"))

    gallery_frame.bind("<Configure>", configure_scroll_region)

    global topPanelGallery
    global selection_label
    selection_label = Label()

    topPanelGallery = Frame(gallery_frame)
    topPanelGallery.grid(row=0, column=0, columnspan=3, pady=10)

    title = Label(topPanelGallery, text='Gallery', compound="left", pady=2, justify="left", highlightthickness=4)
    title.pack(side=LEFT)

    row = 1
    col = 0
    max_cols = 3  # Number of columns in the grid
    thumbnail_size = (150, 150)  # Size of thumbnail images

    global selected_image
    selected_image = None  # Dictionary to track selected images

    def label_action():
        global topPanelGallery
        global selection_label
        global selected_image
        if selected_image != None:
            selection_label.destroy()
            selection_label = Label(topPanelGallery, text="Upload", foreground="blue")
            selection_label.pack(side=RIGHT, expand=True, fill='both')
            selection_label.bind("<Button-1>", lambda e: uploadToStorage("C:/raspberry_images/" + selected_image))
        else:
            selection_label.destroy()

    def toggle_selection(image_label, image_file):
        global selected_image
        if selected_image == image_file:
            image_label.config(highlightthickness=0)
            selected_image = None
            label_action()
        else:
            for widget in gallery_frame.winfo_children():
                if isinstance(widget, Label):
                    widget.config(highlightthickness=0)
            selected_image = image_file
            label_action()
            image_label.config(highlightbackground="blue", highlightthickness=2)
            print(f"Selected image: {selected_image}")

    for image_file in image_files:
        image_path = os.path.join(images_dir, image_file)
        try:
            print(f"Loading image from: {image_path}")  # Debugging line
            image = Image.open(image_path)
            image.thumbnail(thumbnail_size)
            tk_image = ImageTk.PhotoImage(image)

            image_label = Label(gallery_frame, image=tk_image)
            image_label.image = tk_image  # Keep a reference to avoid garbage collection
            image_label.grid(row=row, column=col, padx=5, pady=5)
            image_label.bind("<Button-1>", lambda e, label=image_label, file=image_file: toggle_selection(label, file))

            col += 1
            if col >= max_cols:
                col = 0
                row += 1
        except Exception as e:
            print(f"Error loading image {image_file}: {e}")


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
        cap = cv2.VideoCapture(0)  # Try index 0
        if not cap.isOpened():
            cap = cv2.VideoCapture(1)  # Try index 1 if 0 doesn't work
            if not cap.isOpened():
                cap = cv2.VideoCapture(-1)  # Try index 1 if 0 doesn't work
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

        # Directory to save captured images
        if platform.system() == "Windows":
            save_dir = 'C:/raspberry_images'  # Update this path as needed
        else:  # Assuming it's a Raspberry Pi or Linux-based system
            save_dir = '/home/mehant/Pictures'  # Update this path as needed

        # Create the directory if it does not exist
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        # File path to save the captured image
        image_filename = os.path.join(save_dir, f'captured_frame_{timestamp}.png')

        try:
            # Read a frame from the camera
            ret, frame = cap.read()
            if ret:
                # Save the captured frame as an image file
                cv2.imwrite(image_filename, frame)
                print(f"Image captured and saved as {image_filename}")

                # Update the UI with the captured image
                if os.path.exists(image_filename):
                    image = Image.open(image_filename)
                    tk_image = ImageTk.PhotoImage(image)
                    camera_label.config(image=tk_image)
                    camera_label.image = tk_image
                else:
                    print("Error: Captured image not found.")
            else:
                print("Error: Failed to capture image.")
        except Exception as e:
            print(f"Error capturing image: {e}")
        finally:
            cap.release()  # Release the camera resource

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
root.geometry("800x480")

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
