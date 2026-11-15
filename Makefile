GTFS_URL ?= https://developer.trimet.org/schedule/gtfs.zip
THREE_VERSION ?= 0.170.0
HTTP_PORT ?= 8000

.PHONY: all download serve clean distclean
.DELETE_ON_ERROR:

all: vendor/three.module.js vendor/OrbitControls.js data/portland-space-time.json

download: data/trimet-gtfs.zip

data/trimet-gtfs.zip:
	mkdir -p data
	curl --fail --location --retry 3 --output $@.tmp "$(GTFS_URL)"
	mv $@.tmp $@

vendor/three.module.js:
	mkdir -p vendor
	curl --fail --location --retry 3 --output $@.tmp "https://unpkg.com/three@$(THREE_VERSION)/build/three.module.js"
	mv $@.tmp $@

vendor/OrbitControls.js:
	mkdir -p vendor
	curl --fail --location --retry 3 --output $@.tmp "https://unpkg.com/three@$(THREE_VERSION)/examples/jsm/controls/OrbitControls.js"
	mv $@.tmp $@

data/portland-space-time.json: data/trimet-gtfs.zip scripts/build_data.py
	python3 scripts/build_data.py

serve: all
	python3 -m http.server $(HTTP_PORT)

clean:
	rm -f data/portland-space-time.json visualization-check.png *.tmp data/*.tmp vendor/*.tmp
	rm -rf scripts/__pycache__

distclean: clean
	rm -f data/trimet-gtfs.zip vendor/three.module.js vendor/OrbitControls.js
