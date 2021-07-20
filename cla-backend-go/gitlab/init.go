package gitlab

var gitlabAppPrivateKey string
var gitlabAppID int

// Init initializes the required gitlab variables
func Init(glAppID int, glAppPrivateKey string) {
	gitlabAppPrivateKey = glAppPrivateKey
	gitlabAppID = glAppID
}

func getGitlabAppPrivateKey() string {
	return gitlabAppPrivateKey
}

func getGitlabAppID() int {
	return gitlabAppID
}
