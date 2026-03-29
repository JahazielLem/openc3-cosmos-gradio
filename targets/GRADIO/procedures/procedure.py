# Script Runner test script
cmd("GRADIO EXAMPLE")
wait_check("GRADIO STATUS BOOL == 'FALSE'", 5)
