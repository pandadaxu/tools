#!/usr/bin/env python2.4
import pysdic
import sdict
import hildon
import osso
import gtk

osso_c = osso.Context("sdictviewer", pysdic.version, False)

class HildonSDictViewer(pysdic.SDictViewer):
        
    def create_top_level_widget(self):
        app = hildon.Program()        
        window = hildon.Window()
        gtk.set_application_name(pysdic.app_name)
        self.window_in_fullscreen = False
        window.connect("key-press-event", self.on_key_press)
        window.connect("window-state-event", self.on_window_state_change)
        app.add_window(window)        
        window.connect("destroy", self.destroy)
        return window
    
    def on_window_state_change(self, widget, event, *args):             
         if event.new_window_state & gtk.gdk.WINDOW_STATE_FULLSCREEN:
             self.window_in_fullscreen = True
         else:
             self.window_in_fullscreen = False    
    
    def on_key_press(self, widget, event, *args):
        if event.keyval == gtk.keysyms.F6:
            # The "Full screen" hardware key has been pressed
            if self.window_in_fullscreen:
                self.window.unfullscreen ()
            else:
                self.window.fullscreen ()
    
    def add_menu(self, content_box):        
        main_menu =  gtk.Menu()
        self.window.set_menu(main_menu)                
        for menu in self.create_menus():
            main_menu.append(menu)
        main_menu.show_all()
    
    def create_menus(self):           
        return (self.mi_open, self.mn_remove_item, self.mi_info, self.mi_select_phonetic_font, self.mi_about, self.mi_exit)
    
    
    def create_file_chooser_dlg(self):
        dlg = hildon.FileChooserDialog(self.window, gtk.FILE_CHOOSER_ACTION_OPEN);        
        return dlg
        
if __name__ == "__main__":    
    viewer = HildonSDictViewer()
    viewer.main()