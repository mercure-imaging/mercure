build:
	docker build . -t yarranyu/processing-step:dev

update: build
	nomad job run ../mercure-processor.nomad

dispatch: update
	nomad job dispatch -meta IMAGE_ID=alpine:3.11 -meta PATH=test processing-step
