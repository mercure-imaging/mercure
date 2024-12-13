# Read the version of the mercure source, which will be used for
# tagging the Docker images, unless a tag has been provided 
# through the environment variable MERCURE_TAG
if [ ! -f "app/VERSION" ]; then
    echo "Error: VERSION file missing. Unable to proceed."
    exit 1
fi
VERSION=`cat app/VERSION`
TAG=${MERCURE_TAG:-$VERSION}

echo "Pushing Docker containers for mercure $VERSION"
echo "Using image tag $TAG"
echo ""
read -p "Proceed (y/n)? " ANS
if [ "$ANS" = "y" ]; then
echo ""
else
echo "Aborted."
exit 0
fi
read -p "Push also under tag 'latest' (y/n)? " ANS_LATEST

docker push mercureimaging/mercure-base:$TAG
docker push mercureimaging/mercure-router:$TAG
docker push mercureimaging/mercure-processor:$TAG
docker push mercureimaging/mercure-receiver:$TAG
docker push mercureimaging/mercure-dispatcher:$TAG
docker push mercureimaging/mercure-bookkeeper:$TAG
docker push mercureimaging/mercure-cleaner:$TAG
docker push mercureimaging/mercure-ui:$TAG
docker push mercureimaging/alpine-sshd:latest
docker push mercureimaging/processing-step:$TAG
docker push mercureimaging/mercure-dummy-processor:$TAG
docker push mercureimaging/mercure-worker:$TAG

if [ "$ANS_LATEST" = "y" ]; then
echo "Now pushing images as 'latest'..."
docker push mercureimaging/mercure-base:latest
docker push mercureimaging/mercure-router:latest
docker push mercureimaging/mercure-processor:latest
docker push mercureimaging/mercure-receiver:latest
docker push mercureimaging/mercure-dispatcher:latest
docker push mercureimaging/mercure-bookkeeper:latest
docker push mercureimaging/mercure-cleaner:latest
docker push mercureimaging/mercure-ui:latest
docker push mercureimaging/processing-step:latest
docker push mercureimaging/mercure-dummy-processor:latest
docker push mercureimaging/mercure-worker:latest
fi

echo ""
echo "Done."
echo ""
