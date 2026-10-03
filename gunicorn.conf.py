# Gunicorn lee este archivo solo al arrancar (no hace falta cambiar nada en Render).
#
# Con el modo por defecto ("sync") el servidor atiende UNA petición a la vez:
# mientras espera la respuesta de la base de datos (que está en otro continente
# y tarda cientos de milisegundos) no atiende a nadie más, y todos los usuarios
# hacen fila. Con hilos, mientras una petición espera a la base, las demás
# avanzan.
workers = 1        # el plan gratuito de Render tiene muy poca CPU
threads = 8
worker_class = "gthread"
timeout = 60
