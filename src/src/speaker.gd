@tool
extends Node
class_name Speaker

static func speak(text: String, lang: String = "en-US"):
	if OS.has_feature("web"):
		JavaScriptBridge.eval("""
			(function() {
				var msg = new SpeechSynthesisUtterance();
				msg.text = "%s";
				msg.lang = "%s";
				window.speechSynthesis.speak(msg);
			})();
		""" % [text, lang])
	else:
		# todo check the french version on mac
#        if OS.get_name() == "macOS":
#            var voice = "Thomas"
#            var args = ["-v", voice, text]
#            OS.execute("say", args, [])
#        else:
#            DisplayServer.tts_speak(text, lang)
		const interrupt = true
		DisplayServer.tts_speak(text, lang, 50, 1, 1.1, 1, interrupt)


static func stop_speaking():
	if OS.has_feature("web"):
		JavaScriptBridge.eval("""
			window.speechSynthesis.cancel();
		""")
	else:
		DisplayServer.tts_stop()
