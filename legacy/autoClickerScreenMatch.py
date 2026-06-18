
# -- Auto Clicker Interface -- #

'''

First attempt at an autoclicker, for use with boxed.gg to get half hour gem drops.

'''

import pyautogui
import cv2
import numpy as np
import time

# Disable PyAutoGUI failsafe if needed (moves mouse to corner to stop)
# pyautogui.FAILSAFE = False

def take_screenshot():
    return pyautogui.screenshot()

def find_button_on_screen(template_path, confidence=0.8):
    # Take screenshot
    screenshot = pyautogui.screenshot()
    screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    
    # Load template image
    template = cv2.imread(template_path)
    
    # Template matching
    result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    locations = np.where(result >= confidence)
    
    if len(locations[0]) > 0:
        # Return first match coordinates
        y, x = locations[0][0], locations[1][0]
        return (x, y)
    return None

def click_if_found(template_path):
    location = find_button_on_screen(template_path)
    if location:
        pyautogui.click(location[0], location[1])
        print(f"Clicked at {location}")
        return True
    return False

# Main loop
while True:
    if click_if_found('button_template.png'):
        time.sleep(2)  # Wait after clicking
    time.sleep(1)  # Check every second
