build:
	docker build . -t mercure/processor:dev

update: build
	nomad job run ../mercure-processor.nomad

dispatch: update
	nomad job dispatch -meta IMAGE_ID=alpine:3.11 -meta PATH=test  mercure-processor