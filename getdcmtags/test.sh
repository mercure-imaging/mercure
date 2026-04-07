#!/bin/bash
set -euo pipefail

echo "Testing"
cp test_dcm test_dcm_copy
./getdcmtags test_dcm_copy sender_address sender_aet receiver_aet 0.0.0.0 asdf --set-tag forceKey=forcedValue
uid="1.2.276.0.7230010.3.1.3.9022104837472469675953272569912339663578"
if [ ! -e $uid/$uid#test_dcm_copy.tags ]; then
    echo "Failed to create tags file"
    exit 1
fi


check_key() {
    local key="$1"
    local expected_value="$2"
    local actual_value=$(jq -r ".$key // \"__NULL__\"" "$uid/$uid#test_dcm_copy.tags")
    
    if [ "$actual_value" == "__NULL__" ]; then
        cat $uid/$uid#test_dcm_copy.tags
        echo "Key '$key' not found in the JSON file."
        echo "Test failed"
        exit 1
    elif [ "$actual_value" == "$expected_value" ]; then
        return
        # echo "Key '$key' matches expected value: $actual_value"
    else
        cat $uid/$uid#test_dcm_copy.tags
        echo "Key '$key' does not match. Expected: $expected_value, Actual: $actual_value"
        echo "Test failed"
        exit 1
    fi
}


check_key "Filename" "test_dcm_copy"
check_key "SenderAddress" "sender_address"
check_key "SenderAET" "sender_aet"
check_key "ReceiverAET" "receiver_aet"
check_key "SeriesInstanceUID" "$uid"
check_key "forceKey" "forcedValue"

rm -f test_dcm_copy
rm -rf $uid

echo "Success"