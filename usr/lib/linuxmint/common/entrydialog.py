import gtk, sys

def responseToDialog(entry, dialog, response):
	dialog.response(response)

def showEntryDialog(primary_label="", label_name="", secondary_text="", title=""):
	#base this on a message dialog
	dialog = gtk.MessageDialog(
		None,
		gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
		gtk.MESSAGE_QUESTION,
		gtk.BUTTONS_OK,
		None)
	dialog.set_markup(primary_label)
	dialog.set_title(title)
	#create the text input field
	entry = gtk.Entry()
	#allow the user to press enter to do ok
	entry.connect("activate", responseToDialog, dialog, gtk.RESPONSE_OK)
	#create a horizontal box to pack the entry and a label
	hbox = gtk.HBox()
	hbox.pack_start(gtk.Label(label_name), False, 5, 5)
	hbox.pack_end(entry)
	#some secondary text
	dialog.format_secondary_markup(secondary_text)
	#add it and show it
	dialog.vbox.pack_end(hbox, True, True, 0)
	dialog.show_all()
	#go go go
	dialog.run()
	text = entry.get_text()
	dialog.destroy()
	return text

if __name__ == '__main__':
	if (len(sys.argv) == 5):
		print "%s" % showEntryDialog(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
	else:
		print "%s" % showEntryDialog("<b>Primary</b>", "label:", "<i>secondary</i>", "title")
